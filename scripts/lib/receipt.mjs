import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { testCounts } from "./gate.mjs";
import { createValidator, loadSchemas } from "./schema.mjs";

export const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const schema = loadSchemas().find(
  (entry) => entry.schema.$id === "urn:team6:schema:execution-receipt:v1",
).schema;
const validateShape = createValidator().compile(schema);
const maxBytes = 16 * 1024 * 1024;

export function aggregateStatus(commands) {
  for (const status of ["FAIL", "BLOCKED", "NOT_RUN"]) {
    if (commands.some((command) => command.status === status)) return status;
  }
  return "PASS";
}

export function readBoundedFile(root, path) {
  if (
    isAbsolute(path) ||
    path.includes("\\") ||
    path.split("/").some((part) => part === ".." || part === "." || part === "")
  ) {
    throw new Error("non-canonical relative path");
  }
  const base = realpathSync(root);
  const target = resolve(base, path);
  const actual = realpathSync(target);
  const inside = relative(base, actual);
  if (inside.startsWith(`..${sep}`) || inside === ".." || isAbsolute(inside))
    throw new Error("path escapes repository");
  const stat = lstatSync(target);
  if (!stat.isFile() || stat.size > maxBytes) throw new Error("not a bounded regular file");
  return readFileSync(target);
}

export function fileEvidence(root, path) {
  const bytes = readBoundedFile(root, path);
  return { path, sha256: sha256(bytes), bytes: bytes.length };
}

export function validateReceipt(receipt, { root, verifyFiles = true, verifyInputs = false } = {}) {
  if (!validateShape(receipt)) {
    // Do not include instance values (command arguments may contain sensitive data).
    return validateShape.errors.map((error) => `${error.instancePath || "/"}: ${error.keyword}`);
  }
  const errors = [];
  const start = Date.parse(receipt.startedAt);
  const finish = Date.parse(receipt.finishedAt);
  if (finish < start) errors.push("receipt timestamps reversed");
  const ids = new Set();
  for (const command of receipt.commands) {
    if (ids.has(command.id)) errors.push("duplicate command ID");
    ids.add(command.id);
    const commandStart = Date.parse(command.startedAt);
    const commandFinish = Date.parse(command.finishedAt);
    if (commandFinish < commandStart || commandStart < start || commandFinish > finish) {
      errors.push(`${command.id}: timestamps outside receipt interval`);
    }
    if (
      command.status === "PASS" &&
      (command.exitCode !== 0 || command.signal || !command.output)
    ) {
      errors.push(`${command.id}: PASS requires successful exit and output evidence`);
    }
    if (command.status !== "PASS" && !command.reason.trim())
      errors.push(`${command.id}: reason required`);
    if (command.status === "FAIL" && !(command.exitCode > 0) && !command.tests?.failed) {
      errors.push(`${command.id}: FAIL contradicts successful command`);
    }
    if (command.status === "NOT_RUN" && (command.exitCode > 0 || command.signal)) {
      errors.push(`${command.id}: NOT_RUN contradicts failed or interrupted command`);
    }
    if (command.tests) {
      if (
        command.status === "PASS" &&
        (command.tests.failed || command.tests.skipped || !command.tests.passed)
      ) {
        errors.push(`${command.id}: incomplete tests cannot PASS`);
      }
      if (command.tests.failed && command.status !== "FAIL")
        errors.push(`${command.id}: failed tests require FAIL`);
      if (command.tests.skipped && command.status === "PASS")
        errors.push(`${command.id}: skipped tests cannot PASS`);
    }
  }
  if (receipt.status !== aggregateStatus(receipt.commands))
    errors.push("receipt status contradicts command statuses");
  if (receipt.kind === "milestone" && receipt.status === "PASS") {
    if (!receipt.reviewer?.trim()) errors.push("milestone PASS requires reviewer");
    if (receipt.rollback.status !== "PASS")
      errors.push("milestone PASS requires verified rollback");
  }
  const rollbackCommands = receipt.rollback.commandIds.map((id) =>
    receipt.commands.find((command) => command.id === id),
  );
  if (rollbackCommands.some((command) => !command))
    errors.push("rollback references missing command");
  if (
    receipt.rollback.status === "PASS" &&
    (!rollbackCommands.length || rollbackCommands.some((command) => command?.status !== "PASS"))
  ) {
    errors.push("rollback PASS requires successful command evidence");
  }
  if (verifyFiles) {
    if (!root) throw new Error("root required to verify evidence files");
    const files = [
      ...receipt.artifacts,
      ...receipt.commands.flatMap((command) => (command.output ? [command.output] : [])),
    ];
    if (verifyInputs) files.push(...receipt.inputs);
    for (const evidence of files) {
      try {
        const actual = fileEvidence(root, evidence.path);
        if (actual.sha256 !== evidence.sha256 || actual.bytes !== evidence.bytes)
          errors.push(`${evidence.path}: hash/length mismatch`);
      } catch {
        errors.push(`${evidence.path}: evidence unavailable or unsafe`);
      }
    }
    for (const command of receipt.commands) {
      if (!command.tests || !command.output) continue;
      try {
        const counts = testCounts(readBoundedFile(root, command.output.path).toString("utf8"));
        if (
          !counts ||
          ["passed", "failed", "skipped"].some((key) => counts[key] !== command.tests[key])
        ) {
          errors.push(`${command.id}: test counts contradict output evidence`);
        }
      } catch {
        errors.push(`${command.id}: test output unavailable`);
      }
    }
  }
  return errors;
}
