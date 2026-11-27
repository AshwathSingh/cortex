import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (file) => fs.readFileSync(file, "utf8").trim();
const digest = (file) =>
  createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const alive = (pid) => {
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch {
    return false;
  }
};
const fail = (message) => {
  throw new Error(message);
};

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: "inherit",
    ...options,
  });
  if (result.error || result.status !== 0)
    fail(
      `Command failed: ${command} ${args.join(" ")}. ${result.error?.message ?? "Check the output above."}`,
    );
  return result;
}
function output(command, args, options = {}) {
  return run(command, args, {
    encoding: "utf8",
    stdio: "pipe",
    ...options,
  }).stdout.trim();
}
function runtimeVersions(root) {
  const expectedNode = read(path.join(root, ".nvmrc"));
  if (process.versions.node !== expectedNode)
    fail(
      `Use Node ${expectedNode} (nvm install && nvm use), then rerun npm run setup.`,
    );
  const expectedNpm = JSON.parse(
    read(path.join(root, "package.json")),
  ).packageManager.split("@")[1];
  if (output("npm", ["--version"]) !== expectedNpm)
    fail(`Use npm ${expectedNpm}: npm install -g npm@${expectedNpm}`);
}
function backendPython(root) {
  return (
    process.env.CORTEX_BACKEND_PYTHON ??
    path.join(
      process.env.CORTEX_RUNTIME_ROOT ?? root,
      "backend/.venv/bin/python",
    )
  );
}
function pythonVersion(root, executable) {
  const expected = read(path.join(root, ".python-version"));
  const version = output(executable, [
    "-c",
    "import platform; print(platform.python_version())",
  ]);
  if (version !== expected)
    fail(
      `Use Python ${expected}; ${executable} is ${version}. Set CORTEX_PYTHON to the matching interpreter for setup.`,
    );
}
function stamp(file, hash) {
  fs.writeFileSync(file, `${hash}\n`);
}

export function verifyDependencies(root) {
  const modules = path.join(root, "apps/web/node_modules");
  if (!fs.existsSync(modules))
    fail("Frontend dependencies are missing. Run npm run setup.");
  if (fs.lstatSync(modules).isSymbolicLink())
    fail(
      "node_modules must belong to this checkout. Shared symlinks break Turbopack resolution; npm run setup replaces the link with a local installation.",
    );
  const manifestPath = path.join(root, "apps/web/package.json");
  const lockPath = path.join(root, "apps/web/package-lock.json");
  if (!fs.existsSync(manifestPath) || !fs.existsSync(lockPath))
    fail("Frontend manifest or lockfile is missing.");
  const manifest = JSON.parse(read(manifestPath));
  const lockedManifest = JSON.parse(read(lockPath)).packages[""];
  const normalized = (value) =>
    JSON.stringify(
      Object.entries(value ?? {}).sort(([a], [b]) => a.localeCompare(b)),
    );
  for (const group of [
    "dependencies",
    "devDependencies",
    "optionalDependencies",
  ]) {
    if (normalized(manifest[group]) !== normalized(lockedManifest?.[group]))
      fail(
        "Frontend manifest and package-lock.json differ. Update the lockfile, then run npm run setup.",
      );
  }
  for (const [manifest, marker] of [
    ["apps/web/package-lock.json", "apps/web/node_modules/.cortex-lock.sha256"],
    ["backend/requirements.txt", "backend/.venv/.cortex-requirements.sha256"],
  ]) {
    // Reuse of a Python environment is explicit and requires the same lockfile.
    const markerPath = marker.startsWith("backend/")
      ? path.join(
          path.dirname(path.dirname(backendPython(root))),
          ".cortex-requirements.sha256",
        )
      : path.join(root, marker);
    if (
      !fs.existsSync(markerPath) ||
      read(markerPath) !== digest(path.join(root, manifest))
    )
      fail(
        `${manifest} is not installed at its locked revision. Stop the app and run npm run setup.`,
      );
  }
  for (const name of ["next", "react", "react-dom", "typescript"]) {
    const installed = path.join(modules, name, "package.json");
    const lock = JSON.parse(
      read(path.join(root, "apps/web/package-lock.json")),
    );
    if (
      !fs.existsSync(installed) ||
      JSON.parse(read(installed)).version !==
        lock.packages[`node_modules/${name}`].version
    )
      fail(
        `${name} is missing or differs from package-lock.json. Run npm run setup.`,
      );
  }
}
function environment(root) {
  const file =
    process.env.CORTEX_ENV_FILE ??
    path.join(process.env.CORTEX_RUNTIME_ROOT ?? root, ".env");
  if (!fs.existsSync(file))
    fail(".env is missing. Run npm run setup to generate local configuration.");
  return file;
}
function assertIdle(root) {
  if (fs.existsSync(path.join(root, ".cortex-dev/watchdog.lock")))
    fail(
      "Stop the Cortex watchdog before installing dependencies; its startup lock is held.",
    );
  const pidFile = path.join(root, ".cortex-dev/watchdog.pid");
  if (fs.existsSync(pidFile) && alive(read(pidFile)))
    fail(
      "Stop the running Cortex watchdog before installing dependencies. This prevents installs and service restarts from racing.",
    );
}
export function acquireSetupLock(root) {
  const lock = path.join(root, ".cortex-dev/environment.lock");
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  try {
    fs.mkdirSync(lock);
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    const pidFile = path.join(lock, "pid");
    if (!fs.existsSync(pidFile) || alive(read(pidFile)))
      fail(
        "Another setup is running. Wait for it to finish before starting Cortex.",
      );
    fs.rmSync(lock, { recursive: true });
    fs.mkdirSync(lock);
  }
  fs.writeFileSync(path.join(lock, "pid"), `${process.pid}\n`);
  return () => fs.rmSync(lock, { recursive: true, force: true });
}
export function createEnvironment(root) {
  const file = path.join(root, ".env");
  if (fs.existsSync(file)) return false;
  const password = randomBytes(24).toString("hex");
  const key = randomBytes(32)
    .toString("base64")
    .replaceAll("+", "-")
    .replaceAll("/", "_");
  const contents = read(path.join(root, ".env.example"))
    .replaceAll("YOUR_PASS", password)
    .replaceAll("YOUR_CLIENT_ID", "")
    .replaceAll("YOUR_CLIENT_SECRET", "")
    .replace(/^TOKEN_ENCRYPTION_KEY=.*$/m, `TOKEN_ENCRYPTION_KEY=${key}`);
  fs.writeFileSync(file, `${contents}\n`, { mode: 0o600, flag: "wx" });
  return true;
}
function setup(root) {
  runtimeVersions(root);
  const release = acquireSetupLock(root);
  try {
    assertIdle(root);
    const python = process.env.CORTEX_PYTHON ?? "python3.13";
    pythonVersion(root, python);
    const modules = path.join(root, "apps/web/node_modules");
    if (fs.existsSync(modules) && fs.lstatSync(modules).isSymbolicLink())
      fs.unlinkSync(modules);
    const venv = path.join(root, "backend/.venv");
    if (fs.existsSync(venv) && fs.lstatSync(venv).isSymbolicLink())
      fail(
        "backend/.venv is a shared symlink. Remove the link before setup; each checkout needs its own environment.",
      );
    if (fs.existsSync(venv)) fs.rmSync(venv, { recursive: true });
    run(python, ["-m", "venv", venv]);
    const executable = path.join(venv, "bin/python");
    pythonVersion(root, executable);
    // Exact versions + hashes, and wheels only: no unpinned build dependencies.
    run(
      executable,
      [
        "-m",
        "pip",
        "install",
        "--require-hashes",
        "--only-binary=:all:",
        "-r",
        "backend/requirements.txt",
      ],
      { cwd: root },
    );
    run(executable, ["-m", "pip", "check"]);
    stamp(
      path.join(venv, ".cortex-requirements.sha256"),
      digest(path.join(root, "backend/requirements.txt")),
    );
    run("npm", ["ci", "--prefix", "apps/web"], { cwd: root });
    stamp(
      path.join(modules, ".cortex-lock.sha256"),
      digest(path.join(root, "apps/web/package-lock.json")),
    );
    if (createEnvironment(root))
      console.log(
        "Created .env with unique local credentials. Existing database volumes must use their original credentials.",
      );
    console.log(
      "Dependencies installed from lockfiles. Next: npm run db:setup, then npm run dev:watch.",
    );
  } finally {
    release();
  }
}
export function preflight(root) {
  if (fs.existsSync(path.join(root, ".cortex-dev/environment.lock")))
    fail(
      "Setup is in progress. Wait for npm run setup to finish before starting Cortex.",
    );
  runtimeVersions(root);
  verifyDependencies(root);
  const executable = backendPython(root);
  pythonVersion(root, executable);
  const envFile = environment(root);
  run(executable, ["-m", "scripts.check_environment"], {
    cwd: path.join(root, "backend"),
    env: { ...process.env, CORTEX_ENV_FILE: envFile },
  });
  console.log("Runtime, locked dependencies and backend imports: ready.");
}
function databases(root) {
  preflight(root);
  const args = [
    "compose",
    "--project-directory",
    root,
    "--env-file",
    environment(root),
  ];
  if (process.env.CORTEX_COMPOSE_PROJECT)
    args.push("--project-name", process.env.CORTEX_COMPOSE_PROJECT);
  run("docker", [...args, "up", "-d", "postgres", "neo4j"]);
  run(backendPython(root), ["-m", "scripts.dev_database_setup"], {
    cwd: path.join(root, "backend"),
    env: { ...process.env, CORTEX_ENV_FILE: environment(root) },
  });
}
if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const command = process.argv[2];
    if (command === "setup") setup(ROOT);
    else if (command === "check") preflight(ROOT);
    else if (command === "databases") databases(ROOT);
    else fail("Usage: node scripts/dev_environment.mjs setup|check|databases");
  } catch (error) {
    console.error(`Cortex setup: ${error.message}`);
    process.exitCode = 1;
  }
}
