import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { setTimeout } from "node:timers/promises";
import { fileURLToPath } from "node:url";

// Isolated disposable test database. Never load .env or use an existing application DB.
const root = fileURLToPath(new URL("../", import.meta.url));
const image = "postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193";
const name = `team6-baseline-${randomUUID()}`;
const password = randomUUID();
const docker = (args, extraEnv = {}) =>
  spawnSync("docker", args, {
    cwd: root,
    encoding: "utf8",
    timeout: 30_000,
    maxBuffer: 1024 * 1024,
    env: { ...process.env, ...extraEnv },
  });
const requireSuccess = (result, step) => {
  if (result.status !== 0 || result.error)
    throw new Error(`${step} failed; no receipt PASS claimed`);
  return result.stdout.trim();
};
let created = false;
let cleaned = false;
function cleanup() {
  if (!created || cleaned) return;
  const result = docker(["rm", "--force", "--volumes", name]);
  if (result.status !== 0) {
    console.error(`Cleanup failed for disposable container ${name}`);
    process.exitCode = 1;
  } else {
    cleaned = true;
    console.log("Disposable PostgreSQL removed");
  }
}
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    cleanup();
    process.exit(1);
  });
}
try {
  requireSuccess(docker(["image", "inspect", image]), "Pinned local PostgreSQL image lookup");
  // Create first so failed startup can still be cleaned up using our unique identity.
  requireSuccess(
    docker(
      [
        "create",
        "--pull=never",
        "--name",
        name,
        "--label",
        "team6.purpose=baseline-test",
        "--memory=512m",
        "--cpus=1",
        "--tmpfs",
        "/var/lib/postgresql/data:rw,size=384m",
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_PASSWORD",
        "--env",
        "POSTGRES_DB=team6_baseline",
        image,
      ],
      { POSTGRES_PASSWORD: password },
    ),
    "Disposable PostgreSQL creation",
  );
  created = true;
  requireSuccess(docker(["start", name]), "Disposable PostgreSQL startup");
  const binding = requireSuccess(docker(["port", name, "5432/tcp"]), "Loopback binding lookup");
  if (!/^127\.0\.0\.1:\d+$/.test(binding)) throw new Error("Unexpected database port binding");
  let ready = false;
  for (let attempt = 0; attempt < 40; attempt++) {
    const result = docker([
      "exec",
      name,
      "pg_isready",
      "-h",
      "127.0.0.1",
      "-U",
      "postgres",
      "-d",
      "team6_baseline",
    ]);
    if (result.status === 0) {
      ready = true;
      break;
    }
    await setTimeout(500);
  }
  if (!ready) throw new Error("Disposable PostgreSQL readiness timed out");
  const version = requireSuccess(
    docker([
      "exec",
      name,
      "psql",
      "-U",
      "postgres",
      "-d",
      "team6_baseline",
      "-Atc",
      "SHOW server_version",
    ]),
    "PostgreSQL version query",
  );
  console.log(`PostgreSQL ${version}; pinned image ${image}`);
  const baseline = spawnSync(
    process.execPath,
    ["scripts/capture-baseline.mjs", ...process.argv.slice(2)],
    {
      cwd: root,
      stdio: "inherit",
      timeout: 20 * 60_000,
      env: {
        ...process.env,
        TEST_DATABASE_URL: `postgresql://postgres:${password}@${binding}/team6_baseline`,
      },
    },
  );
  process.exitCode = baseline.status === 0 && !baseline.error ? 0 : 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  cleanup();
}
