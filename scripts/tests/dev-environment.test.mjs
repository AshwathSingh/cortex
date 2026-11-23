import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  verifyDependencies,
  acquireSetupLock,
  createEnvironment,
} from "../dev_environment.mjs";
const repo = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const hash = (value) => createHash("sha256").update(value).digest("hex");
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-setup-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const write = (file, value, mode) => {
    const target = path.join(root, file);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, value, { mode });
  };
  return { root, write };
}
function installed(t) {
  const f = fixture(t),
    packages = {};
  for (const name of ["next", "react", "react-dom", "typescript"]) {
    packages[`node_modules/${name}`] = { version: "1.0.0" };
    f.write(
      `apps/web/node_modules/${name}/package.json`,
      JSON.stringify({ version: "1.0.0" }),
    );
  }
  packages[""] = {};
  f.write("apps/web/package.json", "{}");
  const lock = JSON.stringify({ packages });
  f.write("apps/web/package-lock.json", lock);
  f.write("apps/web/node_modules/.cortex-lock.sha256", hash(lock));
  f.write("backend/requirements.txt", "locked");
  f.write("backend/.venv/.cortex-requirements.sha256", hash("locked"));
  return f;
}
test("accepts a local installation matching both lockfiles", (t) => {
  const { root } = installed(t);
  assert.doesNotThrow(() => verifyDependencies(root));
});
test("rejects a changed dependency lock before startup", (t) => {
  const { root, write } = installed(t);
  write("backend/requirements.txt", "changed");
  assert.throws(() => verifyDependencies(root), /locked revision/);
});
test("rejects incomplete frontend installs", (t) => {
  const { root } = installed(t);
  fs.unlinkSync(path.join(root, "apps/web/node_modules/next/package.json"));
  assert.throws(() => verifyDependencies(root), /next is missing/);
});
test("rejects shared node_modules without touching its target", (t) => {
  const { root, write } = fixture(t);
  write("shared/keep", "preserve");
  fs.mkdirSync(path.join(root, "apps/web"), { recursive: true });
  fs.symlinkSync(
    path.join(root, "shared"),
    path.join(root, "apps/web/node_modules"),
    "dir",
  );
  assert.throws(
    () => verifyDependencies(root),
    /Shared symlinks break Turbopack/,
  );
  assert.equal(
    fs.readFileSync(path.join(root, "shared/keep"), "utf8"),
    "preserve",
  );
});
test("setup lock prevents simultaneous installs and releases cleanly", (t) => {
  const { root } = fixture(t);
  const release = acquireSetupLock(root);
  assert.throws(() => acquireSetupLock(root), /Another setup/);
  release();
  acquireSetupLock(root)();
});
test("generates unique valid local secrets and preserves existing configuration", (t) => {
  const { root, write } = fixture(t);
  write(
    ".env.example",
    "DATABASE_URL=postgresql://cortex:YOUR_PASS@localhost/cortex\nGITHUB_CLIENT_ID=YOUR_CLIENT_ID\nGITHUB_CLIENT_SECRET=YOUR_CLIENT_SECRET\nTOKEN_ENCRYPTION_KEY=\n",
  );
  assert.equal(createEnvironment(root), true);
  const contents = fs.readFileSync(path.join(root, ".env"), "utf8");
  assert.ok(!contents.includes("YOUR_"));
  const key = contents.match(/TOKEN_ENCRYPTION_KEY=(.*)/)[1];
  assert.equal(Buffer.from(key, "base64url").length, 32);
  assert.equal(fs.statSync(path.join(root, ".env")).mode & 0o777, 0o600);
  assert.equal(createEnvironment(root), false);
  assert.equal(fs.readFileSync(path.join(root, ".env"), "utf8"), contents);
});

test("watchdog exits on SIGTERM and stops its children instead of respawning", async (t) => {
  const { root, write } = fixture(t);
  write(
    "scripts/dev_watchdog.sh",
    fs.readFileSync(path.join(repo, "scripts/dev_watchdog.sh")),
  );
  write("apps/web/node_modules/next/dist/bin/next", "");
  write(".env", "# Test configuration\n");
  const server =
    '#!/usr/bin/env bash\nif [[ "${1:-}" == */dev_environment.mjs ]]; then exit 0; fi\nname="${CORTEX_TEST_NAME:-frontend}"\nprintf "%s" "$$" > "$CORTEX_TEST_ROOT/$name.pid"\ntrap \'rm -f "$CORTEX_TEST_ROOT/$name.pid"; exit 0\' TERM INT\nwhile true; do sleep 0.1; done\n';
  write("fake-node", server, 0o755);
  write(
    "backend/.venv/bin/python",
    server.replace('name="${CORTEX_TEST_NAME:-frontend}"', 'name="backend"'),
    0o755,
  );
  write(
    "bin/curl",
    '#!/usr/bin/env bash\nfor last; do :; done\ncase "$last" in frontend) file=frontend;; *) file=backend;; esac\n[[ -f "$CORTEX_TEST_ROOT/$file.pid" ]] && kill -0 "$(cat "$CORTEX_TEST_ROOT/$file.pid")" 2>/dev/null\n',
    0o755,
  );
  const child = spawn("bash", [path.join(root, "scripts/dev_watchdog.sh")], {
    env: {
      ...process.env,
      PATH: `${root}/bin:${process.env.PATH}`,
      CORTEX_RUNTIME_ROOT: root,
      CORTEX_TEST_ROOT: root,
      CORTEX_NODE_BINARY: path.join(root, "fake-node"),
      CORTEX_FRONTEND_HEALTH_URL: "frontend",
      CORTEX_BACKEND_HEALTH_URL: "backend",
      CORTEX_DATABASE_HEALTH_URL: "backend",
      CORTEX_WATCH_INTERVAL_SECONDS: "1",
    },
    stdio: "pipe",
  });
  let log = "";
  child.stdout.on("data", (x) => (log += x));
  child.stderr.on("data", (x) => (log += x));
  t.after(() => {
    if (child.exitCode === null) child.kill("SIGKILL");
  });
  const deadline = Date.now() + 5000;
  while (
    (!fs.existsSync(path.join(root, "frontend.pid")) ||
      !fs.existsSync(path.join(root, "backend.pid"))) &&
    Date.now() < deadline
  )
    await new Promise((r) => setTimeout(r, 25));
  assert.ok(fs.existsSync(path.join(root, "frontend.pid")), log);
  assert.ok(
    fs.existsSync(path.join(root, "backend.pid")),
    log +
      "\n" +
      fs.readFileSync(path.join(root, ".cortex-dev/backend.log"), "utf8"),
  );
  const second = spawnSync(
    "bash",
    [path.join(root, "scripts/dev_watchdog.sh")],
    {
      env: {
        ...process.env,
        CORTEX_WATCH_LOG_DIR: path.join(root, ".cortex-dev"),
      },
      encoding: "utf8",
    },
  );
  assert.equal(second.status, 1);
  assert.match(second.stderr, /already running/);
  const exited = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGTERM");
  await Promise.race([
    exited,
    new Promise((_, reject) =>
      setTimeout(() => reject(Error(`Shutdown timed out: ${log}`)), 6000),
    ),
  ]);
  assert.equal(child.exitCode, 143, log);
  assert.ok(!fs.existsSync(path.join(root, "frontend.pid")), log);
  assert.ok(!fs.existsSync(path.join(root, "backend.pid")), log);
  assert.ok(!fs.existsSync(path.join(root, ".cortex-dev/watchdog.pid")), log);
});

test("rejects a manifest changed without its lockfile", (t) => {
  const { root, write } = installed(t);
  write(
    "apps/web/package.json",
    JSON.stringify({ dependencies: { next: "2.0.0" } }),
  );
  assert.throws(
    () => verifyDependencies(root),
    /manifest and package-lock.json differ/,
  );
});
