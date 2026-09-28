import assert from "node:assert/strict";
import { mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { checkSchemas } from "../check-schemas.mjs";
import { aggregateStatus, fileEvidence, validateReceipt } from "../lib/receipt.mjs";
import { schemaConventions } from "../lib/schema.mjs";

const root = mkdtempSync(join(tmpdir(), "team6-receipt-"));
after(() => rmSync(root, { recursive: true, force: true }));
writeFileSync(join(root, "output.log"), " Tests 1 passed (1)\n");
const timestamp = "2026-09-26T18:00:00.000Z";
function fixture() {
  return {
    receiptVersion: "execution.v1",
    kind: "gate",
    taskId: "M0.4",
    baselineGitSha: "a".repeat(40),
    worktreeStatus: "",
    owner: "Platform/build",
    reviewer: null,
    status: "PASS",
    startedAt: timestamp,
    finishedAt: timestamp,
    environment: { node: "v24.18.0", platform: "linux", arch: "x64" },
    versions: { pnpm: "9.15.0", python: "Python 3.14.4" },
    commands: [
      {
        id: "contract-tests",
        command: ["node", "--test"],
        status: "PASS",
        exitCode: 0,
        signal: null,
        startedAt: timestamp,
        finishedAt: timestamp,
        output: fileEvidence(root, "output.log"),
        tests: { passed: 1, failed: 0, skipped: 0 },
        reason: "",
      },
    ],
    artifacts: [],
    inputs: [],
    limitations: ["Local gate only"],
    rollback: { status: "NOT_RUN", reason: "No runtime mutation", commandIds: [] },
  };
}
const validate = (receipt) => validateReceipt(receipt, { root });

test("repository schema compilation is deterministic and strict", () => {
  assert.ok(checkSchemas() > 0);
  assert.equal(checkSchemas(), checkSchemas());
  assert.ok(
    schemaConventions({
      type: "object",
      properties: { a: { type: "string" }, b: { type: "array" } },
    }).length >= 4,
  );
});

test("accepts valid gate evidence without claiming milestone review", () => {
  assert.deepEqual(validate(fixture()), []);
  const receipt = fixture();
  receipt.kind = "milestone";
  assert.ok(validate(receipt).some((error) => error.includes("reviewer")));
  assert.ok(validate(receipt).some((error) => error.includes("rollback")));
});

test("rejects unknown versions, fields, oversized values and invalid timestamps", () => {
  for (const change of [
    (r) => {
      r.receiptVersion = "execution.v2";
    },
    (r) => {
      r.authority = true;
    },
    (r) => {
      r.commands[0].trusted = true;
    },
    (r) => {
      r.owner = "x".repeat(257);
    },
    (r) => {
      r.startedAt = "2026-02-30T00:00:00Z";
    },
    (r) => {
      r.startedAt = "2026-09-26T18:00:00+02:00";
    },
    (r) => {
      r.finishedAt = "2026-09-25T00:00:00Z";
    },
    (r) => {
      r.commands[0].startedAt = "2026-09-25T00:00:00Z";
    },
  ]) {
    const receipt = fixture();
    change(receipt);
    assert.ok(validate(receipt).length > 0);
  }
});

test("rejects hash/length substitution, missing evidence and unsafe file paths", () => {
  symlinkSync(tmpdir(), join(root, "outside"));
  for (const change of [
    (r) => {
      r.commands[0].output.sha256 = "b".repeat(64);
    },
    (r) => {
      r.commands[0].output.bytes += 1;
    },
    (r) => {
      r.commands[0].output.path = "missing.log";
    },
    (r) => {
      r.commands[0].output.path = "../outside.log";
    },
    (r) => {
      r.commands[0].output.path = "/etc/passwd";
    },
    (r) => {
      r.commands[0].output = null;
    },
  ]) {
    const receipt = fixture();
    change(receipt);
    assert.ok(validate(receipt).length > 0);
  }
  const outside = mkdtempSync(join(tmpdir(), "team6-external-"));
  try {
    writeFileSync(join(outside, "proof.log"), "proof");
    symlinkSync(outside, join(root, "linked"));
    assert.throws(() => fileEvidence(root, "linked/proof.log"), /escapes/);
  } finally {
    rmSync(outside, { recursive: true, force: true });
  }
});

test("cannot promote skipped, failed, interrupted or absent tests to PASS", () => {
  for (const change of [
    (r) => {
      r.commands[0].tests.skipped = 1;
    },
    (r) => {
      r.commands[0].tests.failed = 1;
    },
    (r) => {
      r.commands[0].tests.passed = 0;
    },
    (r) => {
      r.commands[0].exitCode = 1;
    },
    (r) => {
      r.commands[0].signal = "SIGTERM";
    },
    (r) => {
      r.commands[0].status = "NOT_RUN";
    },
  ]) {
    const receipt = fixture();
    change(receipt);
    assert.ok(validate(receipt).length > 0);
  }
});

test("rejects test counters that disagree with the verified log", () => {
  const receipt = fixture();
  receipt.commands[0].tests.passed = 2;
  assert.ok(validate(receipt).some((error) => error.includes("contradict output")));
});

test("all non-PASS states remain explicit, with deterministic severity", () => {
  for (const status of ["FAIL", "BLOCKED", "NOT_RUN"]) {
    const receipt = fixture();
    receipt.status = receipt.commands[0].status = status;
    receipt.commands[0].reason = "Gate incomplete";
    receipt.commands[0].exitCode = status === "FAIL" ? 1 : null;
    receipt.commands[0].tests = null;
    assert.deepEqual(validate(receipt), []);
  }
  assert.equal(aggregateStatus([{ status: "PASS" }, { status: "NOT_RUN" }]), "NOT_RUN");
  assert.equal(aggregateStatus([{ status: "BLOCKED" }, { status: "FAIL" }]), "FAIL");
});

test("rejects duplicate command IDs and invented rollback proof", () => {
  const receipt = fixture();
  receipt.commands.push(structuredClone(receipt.commands[0]));
  assert.ok(validate(receipt).includes("duplicate command ID"));
  receipt.commands.pop();
  receipt.kind = "milestone";
  receipt.reviewer = "Example reviewer (fixture only)";
  receipt.rollback.status = "PASS";
  receipt.rollback.commandIds = ["invented"];
  assert.ok(validate(receipt).length > 0);
  receipt.rollback.commandIds = ["contract-tests"];
  assert.deepEqual(validate(receipt), []);
});

test("historical input hashes are checked only when explicitly requested", () => {
  const receipt = fixture();
  receipt.inputs.push({ ...fileEvidence(root, "output.log"), sha256: "b".repeat(64) });
  assert.deepEqual(validate(receipt), []);
  assert.ok(
    validateReceipt(receipt, { root, verifyInputs: true }).some((error) =>
      error.includes("mismatch"),
    ),
  );
});
