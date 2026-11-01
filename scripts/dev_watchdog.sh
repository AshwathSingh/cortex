#!/usr/bin/env bash

set -u
set -o pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
runtime_root="${CORTEX_RUNTIME_ROOT:-$repo_root}"
env_file="${CORTEX_ENV_FILE:-$runtime_root/.env}"
backend_python="${CORTEX_BACKEND_PYTHON:-$runtime_root/backend/.venv/bin/python}"
node_binary="${CORTEX_NODE_BINARY:-$(command -v node || true)}"

frontend_port="${CORTEX_FRONTEND_PORT:-3000}"
backend_port="${CORTEX_BACKEND_PORT:-8000}"
bind_host="${CORTEX_BIND_HOST:-127.0.0.1}"
watch_interval="${CORTEX_WATCH_INTERVAL_SECONDS:-5}"
startup_grace="${CORTEX_WATCH_STARTUP_GRACE_SECONDS:-10}"
log_dir="${CORTEX_WATCH_LOG_DIR:-$repo_root/.cortex-dev}"

frontend_health_url="${CORTEX_FRONTEND_HEALTH_URL:-http://127.0.0.1:$frontend_port/login}"
backend_health_url="${CORTEX_BACKEND_HEALTH_URL:-http://127.0.0.1:$backend_port/health}"
database_health_url="${CORTEX_DATABASE_HEALTH_URL:-http://127.0.0.1:$backend_port/api/health/database}"

frontend_pid=""
backend_pid=""
frontend_started_at=0
backend_started_at=0
cleanup_started=0
database_unhealthy_reported=0

usage() {
  cat <<'EOF'
Usage: npm run dev:watch [-- --check]

Runs a foreground watchdog for the Cortex frontend and backend. It restarts only
processes that it started and leaves unrelated processes untouched.

Options:
  --check   Check frontend, backend, and database health once, then exit.
  --help    Show this help text.

Common overrides:
  CORTEX_RUNTIME_ROOT                 Checkout containing .env and backend/.venv
  CORTEX_ENV_FILE                     Explicit environment file
  CORTEX_BACKEND_PYTHON               Explicit Python executable
  CORTEX_BIND_HOST                    Bind address (default: 127.0.0.1)
  CORTEX_WATCH_INTERVAL_SECONDS       Health-check interval (default: 5)
  CORTEX_WATCH_STARTUP_GRACE_SECONDS  Startup grace period (default: 10)
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  log "ERROR: $*" >&2
  exit 1
}

require_positive_integer() {
  local name="$1"
  local value="$2"

  case "$value" in
    ''|*[!0-9]*) fail "$name must be a positive integer." ;;
    0) fail "$name must be greater than zero." ;;
  esac
}

is_healthy() {
  curl --fail --silent --show-error --max-time 3 --output /dev/null "$1" 2>/dev/null
}

pid_is_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

stop_owned_process() {
  local name="$1"
  local pid="$2"
  local attempt

  if ! pid_is_alive "$pid"; then
    return
  fi

  log "Stopping $name (PID $pid)."
  kill "$pid" 2>/dev/null || true

  for attempt in 1 2 3 4 5; do
    if ! pid_is_alive "$pid"; then
      wait "$pid" 2>/dev/null || true
      return
    fi
    sleep 1
  done

  log "$name did not stop cleanly; terminating PID $pid."
  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  if [[ "$cleanup_started" -eq 1 ]]; then
    return
  fi
  cleanup_started=1
  trap - EXIT INT TERM

  stop_owned_process "frontend" "$frontend_pid"
  stop_owned_process "backend" "$backend_pid"
  rm -f "$log_dir/watchdog.pid"
}

start_frontend() {
  [[ -n "$node_binary" ]] || fail "Node.js was not found on PATH."
  [[ -f "$repo_root/apps/web/node_modules/next/dist/bin/next" ]] || \
    fail "Frontend dependencies are missing. Run npm ci --prefix apps/web."

  log "Starting frontend on port $frontend_port."
  (
    cd "$repo_root/apps/web" || exit 1
    exec "$node_binary" node_modules/next/dist/bin/next dev \
      --hostname "$bind_host" --port "$frontend_port"
  ) >>"$log_dir/frontend.log" 2>&1 &
  frontend_pid=$!
  frontend_started_at=$SECONDS
}

start_backend() {
  local env_args=()

  [[ -x "$backend_python" ]] || \
    fail "Backend Python was not found at $backend_python. Set CORTEX_RUNTIME_ROOT or CORTEX_BACKEND_PYTHON."

  if [[ ! -f "$env_file" ]]; then
    log "WARNING: $env_file was not found; starting with default backend configuration."
  else
    env_args=(--env-file "$env_file")
  fi

  log "Starting backend on port $backend_port."
  (
    cd "$repo_root/backend" || exit 1
    exec "$backend_python" -m uvicorn app.main:app --reload \
      "${env_args[@]}" --host "$bind_host" --port "$backend_port"
  ) >>"$log_dir/backend.log" 2>&1 &
  backend_pid=$!
  backend_started_at=$SECONDS
}

ensure_frontend() {
  if is_healthy "$frontend_health_url"; then
    return
  fi

  if ! pid_is_alive "$frontend_pid"; then
    wait "$frontend_pid" 2>/dev/null || true
    frontend_pid=""
    start_frontend
    return
  fi

  if (( SECONDS - frontend_started_at >= startup_grace )); then
    log "Frontend stayed unhealthy beyond the startup grace period; restarting it."
    stop_owned_process "frontend" "$frontend_pid"
    frontend_pid=""
    start_frontend
  fi
}

ensure_backend() {
  if is_healthy "$backend_health_url"; then
    return
  fi

  if ! pid_is_alive "$backend_pid"; then
    wait "$backend_pid" 2>/dev/null || true
    backend_pid=""
    start_backend
    return
  fi

  if (( SECONDS - backend_started_at >= startup_grace )); then
    log "Backend stayed unhealthy beyond the startup grace period; restarting it."
    stop_owned_process "backend" "$backend_pid"
    backend_pid=""
    start_backend
  fi
}

report_database_health() {
  if is_healthy "$database_health_url"; then
    if [[ "$database_unhealthy_reported" -eq 1 ]]; then
      log "Database connection recovered."
    fi
    database_unhealthy_reported=0
    return
  fi

  if [[ "$database_unhealthy_reported" -eq 0 ]]; then
    log "WARNING: PostgreSQL health check failed. The watchdog will keep the app processes running."
    database_unhealthy_reported=1
  fi
}

check_once() {
  local status=0

  if is_healthy "$frontend_health_url"; then
    log "Frontend: healthy ($frontend_health_url)"
  else
    log "Frontend: unavailable ($frontend_health_url)"
    status=1
  fi

  if is_healthy "$backend_health_url"; then
    log "Backend: healthy ($backend_health_url)"
  else
    log "Backend: unavailable ($backend_health_url)"
    status=1
  fi

  if is_healthy "$database_health_url"; then
    log "PostgreSQL: healthy ($database_health_url)"
  else
    log "PostgreSQL: unavailable ($database_health_url)"
    status=1
  fi

  return "$status"
}

require_positive_integer "CORTEX_WATCH_INTERVAL_SECONDS" "$watch_interval"
require_positive_integer "CORTEX_WATCH_STARTUP_GRACE_SECONDS" "$startup_grace"
command -v curl >/dev/null 2>&1 || fail "curl is required."

case "${1:-}" in
  --check) check_once; exit $? ;;
  --help|-h) usage; exit 0 ;;
  '') ;;
  *) usage >&2; exit 2 ;;
esac

mkdir -p "$log_dir"

if [[ -f "$log_dir/watchdog.pid" ]]; then
  existing_watchdog_pid="$(cat "$log_dir/watchdog.pid" 2>/dev/null || true)"
  if [[ "$existing_watchdog_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_watchdog_pid" 2>/dev/null; then
    fail "A Cortex watchdog is already running with PID $existing_watchdog_pid."
  fi
fi

printf '%s\n' "$$" >"$log_dir/watchdog.pid"
trap cleanup EXIT INT TERM

log "Watching Cortex every ${watch_interval}s. Logs: $log_dir"

if is_healthy "$frontend_health_url"; then
  log "Frontend is already healthy; monitoring the existing service."
else
  start_frontend
fi

if is_healthy "$backend_health_url"; then
  log "Backend is already healthy; monitoring the existing service."
else
  start_backend
fi

while true; do
  ensure_frontend
  ensure_backend
  report_database_health
  sleep "$watch_interval"
done
