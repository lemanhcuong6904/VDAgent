import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Code rollback rehearsal for M2..M14. All milestone work sits on top of one baseline commit, so
// rolling back any milestone means redeploying that commit against a database that already has
// the newer (additive) migrations. This proves exactly that:
// 1. apply the current migrations to the disposable TEST_DATABASE_URL;
// 2. export the baseline commit into a temp directory;
// 3. run the baseline typecheck and test suite against the already-migrated database.
// It does not prove image rollback, data restore or a clean dependency reinstall.
const root = fileURLToPath(new URL("../", import.meta.url));
const baseline = "b7bd2734fc3d50975ee71c3b00ff4b164bb43804";
const directory = mkdtempSync(join(tmpdir(), "team6-rollback-"));
const run = (args, cwd) => {
  const result = spawnSync(args[0], args.slice(1), {
    cwd,
    stdio: "inherit",
    timeout: 300_000,
    env: process.env,
  });
  if (result.status !== 0 || result.error) throw new Error(`Failed: ${args.join(" ")}`);
};
try {
  if (!process.env.TEST_DATABASE_URL)
    throw new Error("Rollback rehearsal requires a disposable TEST_DATABASE_URL");
  run(
    [
      "node",
      "--import",
      "tsx",
      "--eval",
      `import pg from "pg";
       import { migrateDatabase } from "./src/database.ts";
       const pool = new pg.Pool({ connectionString: process.env.TEST_DATABASE_URL });
       await migrateDatabase(pool);
       await pool.end();`,
    ],
    root,
  );
  const archive = execFileSync("git", ["archive", "--format=tar", baseline], { cwd: root });
  execFileSync("tar", ["-x", "-C", directory], { input: archive });
  // Installed libraries are reused read-only; this is not a clean install proof.
  symlinkSync(join(root, "node_modules"), join(directory, "node_modules"), "dir");
  symlinkSync(join(root, "frontend/node_modules"), join(directory, "frontend/node_modules"), "dir");
  run(["corepack", "pnpm", "check"], directory);
  run(["corepack", "pnpm", "test"], directory);
  console.log(
    `Rollback rehearsal PASS: baseline ${baseline.slice(0, 7)} typechecks and passes its tests on a database migrated to the current head`,
  );
  console.log("Scope: code rollback only; no image, data restore or clean reinstall claimed");
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  rmSync(directory, { recursive: true, force: true });
}
