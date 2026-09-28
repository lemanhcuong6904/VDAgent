import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { classifyGate, testCounts } from "./lib/gate.mjs";
import { aggregateStatus, fileEvidence, validateReceipt } from "./lib/receipt.mjs";

// Fixed commands only. Never load .env or record the process environment.
const root = fileURLToPath(new URL("../", import.meta.url));
const option = (name) =>
  process.argv.find((arg) => arg.startsWith(`--${name}=`))?.slice(name.length + 3);
const taskId = option("task") ?? "M0.7";
if (!/^M[0-9]+(?:\.[0-9]+)?$/.test(taskId)) throw new Error("Invalid --task milestone ID");
// Optional milestone rollback rehearsal; M0 keeps its original environment switch.
const rollbackScript =
  option("rollback") ??
  (process.env.M0_REHEARSE_ROLLBACK === "1" ? "scripts/rehearse-m0-rollback.mjs" : undefined);
if (rollbackScript && !/^scripts\/rehearse-(?:m[0-9]+-)?rollback\.mjs$/.test(rollbackScript))
  throw new Error("Invalid --rollback script");
const reviewer = option("reviewer") ?? null;
const startedAt = new Date().toISOString();
const captureId = `${taskId.split(".")[0]}-${startedAt.replaceAll(/[:.]/g, "-")}`;
const directory = `docs/execution/runs/${captureId}`;
const receiptPath = `docs/execution/receipts/${captureId}.json`;
const run = (command, args) =>
  spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    timeout: 300_000,
    maxBuffer: 16 * 1024 * 1024,
    env: { ...process.env, NO_COLOR: "1", FORCE_COLOR: "0" },
  });
const version = (command, args) => {
  const result = run(command, args);
  return result.status === 0 ? result.stdout.trim() : "UNAVAILABLE";
};
const baselineGitSha = version("git", ["rev-parse", "HEAD"]);
const worktreeStatus = version("git", ["status", "--short"]);
const tracked = run("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]);
if (tracked.status !== 0) throw new Error("Cannot enumerate baseline inputs");
const inputs = [];
for (const path of [...new Set(tracked.stdout.split("\0").filter(Boolean))].sort()) {
  if (path.startsWith("docs/execution/") && path !== "docs/execution/README.md") continue;
  if (path === ".env" || /\.log$/.test(path)) continue;
  try {
    inputs.push(fileEvidence(root, path));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}
mkdirSync(resolve(root, directory), { recursive: true });
const commands = [];
const governanceTests = readdirSync(resolve(root, "scripts/tests"))
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => `scripts/tests/${name}`);
for (const [id, command, args] of [
  ["inventory-check", "node", ["scripts/inventory.mjs"]],
  ["boundary-check", "node", ["scripts/check-boundaries.mjs"]],
  ["secret-check", "node", ["scripts/check-secrets.mjs"]],
  ["dependency-check", "node", ["scripts/check-dependencies.mjs"]],
  ["schema-check", "node", ["scripts/check-schemas.mjs"]],
  ["versions-check", "corepack", ["pnpm", "versions:check"]],
  ["python-package", "python3", ["scripts/check-python-package.py"]],
  ["governance-tests", "node", ["--test", "--test-reporter=tap", ...governanceTests]],
  ...(rollbackScript ? [["rollback-tests", "node", [rollbackScript]]] : []),
  ["typecheck", "corepack", ["pnpm", "check"]],
  ["lint", "corepack", ["pnpm", "lint"]],
  ["backend-tests", "corepack", ["pnpm", "test"]],
  ["frontend-build", "corepack", ["pnpm", "frontend:build"]],
  ["frontend-tests", "npm", ["--prefix", "frontend", "test"]],
  ["diff-check", "git", ["diff", "--check"]],
]) {
  const start = new Date().toISOString();
  const result = run(command, args);
  const combined = Buffer.from(`${result.stdout ?? ""}${result.stderr ?? ""}`);
  if (combined.length > 16 * 1024 * 1024) result.error = new Error("Output exceeds evidence cap");
  const output = combined.subarray(0, 16 * 1024 * 1024);
  const path = `${directory}/${id}.log`;
  writeFileSync(resolve(root, path), output, { flag: "wx" });
  const expectsTests = id.endsWith("tests");
  const tests = expectsTests ? testCounts(output.toString("utf8")) : null;
  const classification = classifyGate(result, tests, expectsTests);
  commands.push({
    id,
    command: [command, ...args],
    ...classification,
    tests,
    exitCode: result.status,
    signal: result.signal,
    startedAt: start,
    finishedAt: new Date().toISOString(),
    output: fileEvidence(root, path),
  });
  console.log(`${id}: ${classification.status}`);
}
const artifacts = ["docs/execution/inventory.json", "docs/execution/dependency-bom.json"].map(
  (path) => {
    const snapshot = `${directory}/${path.split("/").at(-1)}`;
    copyFileSync(resolve(root, path), resolve(root, snapshot));
    return fileEvidence(root, snapshot);
  },
);
const receipt = {
  receiptVersion: "execution.v1",
  kind: reviewer ? "milestone" : "gate",
  taskId,
  baselineGitSha,
  worktreeStatus,
  owner: "Platform/build",
  reviewer,
  status: aggregateStatus(commands),
  startedAt,
  finishedAt: new Date().toISOString(),
  environment: { node: process.version, platform: process.platform, arch: process.arch },
  versions: {
    pnpm: version("corepack", ["pnpm", "--version"]),
    python: version("python3", ["--version"]),
  },
  commands,
  artifacts,
  inputs,
  limitations: [
    "Local command evidence only; mocked dependencies do not prove live service behavior.",
    "No container, model-provider, capacity, recovery or production gate is claimed.",
    reviewer
      ? "Technical self-review recorded by the capture operator; independent human/release approval pending."
      : "Unreviewed gate capture; not a milestone completion or release approval.",
  ],
  rollback: {
    status: commands.find((command) => command.id === "rollback-tests")?.status ?? "NOT_RUN",
    reason: rollbackScript
      ? `Local rehearsal via ${rollbackScript}; no production image/data rollback claimed.`
      : "No rollback rehearsal requested for this capture.",
    commandIds: commands
      .filter((command) => command.id === "rollback-tests")
      .map((command) => command.id),
  },
};
const errors = validateReceipt(receipt, { root, verifyInputs: true });
if (errors.length) throw new Error(`Invalid receipt: ${errors.join("; ")}`);
mkdirSync(resolve(root, "docs/execution/receipts"), { recursive: true });
// Format through stdin: receipts are excluded from lint so recorded hashes stay stable.
const formatting = spawnSync(
  "corepack",
  ["pnpm", "exec", "biome", "format", "--stdin-file-path", "receipt.json"],
  { cwd: root, input: `${JSON.stringify(receipt, null, 2)}\n`, encoding: "utf8" },
);
if (formatting.status !== 0) console.error("Receipt formatting failed; writing unformatted JSON.");
writeFileSync(
  resolve(root, receiptPath),
  formatting.status === 0 ? formatting.stdout : `${JSON.stringify(receipt, null, 2)}\n`,
  { flag: "wx" },
);
console.log(`Receipt: ${receiptPath}`);
process.exitCode = receipt.status === "PASS" && formatting.status === 0 ? 0 : 1;
