# cortex
a single source of truth across sources for teams 

## Keep the local app running

Run the development watchdog from the repository root:

```bash
npm run dev:watch
```

It monitors the frontend and backend health endpoints, restarts failed services,
and writes logs to `.cortex-dev/`. Press `Ctrl+C` to stop services started by the
watchdog. Use `npm run dev:watch -- --check` for a one-time health check.

An isolated worktree can reuse another checkout's `.env` and Python environment:

```bash
CORTEX_RUNTIME_ROOT=/path/to/configured/cortex npm run dev:watch
```
