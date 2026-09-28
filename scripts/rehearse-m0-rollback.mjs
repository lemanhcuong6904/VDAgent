import { execFileSync, spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { sha256 } from "./lib/receipt.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const baseline = "b7bd2734fc3d50975ee71c3b00ff4b164bb43804";
const runtimePaths = [
  "src",
  "db",
  "sdk/python/agent_platform",
  "sdk/python/examples",
  "test",
  "frontend/src",
];
const configPaths = [
  "Dockerfile",
  "docker-compose.yml",
  "package.json",
  "pnpm-lock.yaml",
  "frontend/package.json",
  "frontend/package-lock.json",
  "sdk/python/pyproject.toml",
];
const directory = mkdtempSync(join(tmpdir(), "team6-m0-rollback-"));
try {
  if (!process.env.TEST_DATABASE_URL)
    throw new Error("Rollback integration rehearsal requires disposable TEST_DATABASE_URL");
  execFileSync("git", ["diff", "--exit-code", baseline, "--", ...runtimePaths], {
    cwd: root,
    stdio: "pipe",
  });
  for (const path of [
    "src",
    "db",
    "sdk",
    "test",
    "frontend",
    "tsconfig.json",
    "biome.json",
    ...configPaths.filter((path) => !path.startsWith("frontend/")),
  ]) {
    cpSync(join(root, path), join(directory, path), {
      recursive: true,
      filter: (source) =>
        !source.split("/").some((part) => ["node_modules", "dist", "__pycache__"].includes(part)),
    });
  }
  for (const path of configPaths) {
    const original = execFileSync("git", ["show", `${baseline}:${path}`], { cwd: root });
    writeFileSync(join(directory, path), original);
    if (sha256(readFileSync(join(directory, path))) !== sha256(original))
      throw new Error(`Rollback hash mismatch: ${path}`);
  }
  // Installed libraries are reused read-only; this is not a clean install or image rollback proof.
  symlinkSync(join(root, "node_modules"), join(directory, "node_modules"), "dir");
  symlinkSync(join(root, "frontend/node_modules"), join(directory, "frontend/node_modules"), "dir");
  for (const args of [
    ["pnpm", "check"],
    ["pnpm", "test"],
  ]) {
    const result = spawnSync("corepack", args, {
      cwd: directory,
      stdio: "inherit",
      timeout: 180_000,
      env: process.env,
    });
    if (result.status !== 0 || result.error) throw new Error("Restored baseline command failed");
  }
  console.log(
    `M0 rollback rehearsal PASS: ${configPaths.length} restored config hashes; runtime unchanged; typecheck and PostgreSQL tests passed`,
  );
  console.log(
    "Scope: local config/tooling removal only; no production image/database rollback or clean dependency reinstall claimed",
  );
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  rmSync(directory, { recursive: true, force: true });
}
