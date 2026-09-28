import assert from "node:assert/strict";
import { test } from "node:test";
import { classifyGate, testCounts } from "../lib/gate.mjs";

test("reads pinned Vitest and Node TAP summaries including todo tests", () => {
  assert.deepEqual(
    testCounts(" Test Files  22 passed | 2 skipped (24)\n      Tests  62 passed | 5 skipped (67)"),
    { passed: 62, failed: 0, skipped: 5 },
  );
  assert.deepEqual(testCounts(" Tests 2 passed | 1 failed | 3 todo (6)"), {
    passed: 2,
    failed: 1,
    skipped: 3,
  });
  assert.deepEqual(testCounts("# pass 8\n# fail 0\n# skipped 1\n# todo 2\n"), {
    passed: 8,
    failed: 0,
    skipped: 3,
  });
  assert.equal(testCounts("Test Files 1 passed"), null);
});

test("unknown output or incomplete execution never becomes PASS", () => {
  const ok = { status: 0, signal: null };
  const counts = { passed: 1, failed: 0, skipped: 0 };
  assert.equal(classifyGate(ok, null, true).status, "BLOCKED");
  assert.equal(classifyGate(ok, { ...counts, skipped: 1 }, true).status, "NOT_RUN");
  assert.equal(classifyGate(ok, { ...counts, failed: 1 }, true).status, "FAIL");
  assert.equal(classifyGate({ ...ok, signal: "SIGTERM" }, counts, true).status, "BLOCKED");
  assert.equal(
    classifyGate({ ...ok, error: new Error("timeout") }, counts, true).status,
    "BLOCKED",
  );
  assert.equal(classifyGate({ ...ok, status: 1 }, counts, true).status, "FAIL");
  assert.equal(classifyGate(ok, { ...counts, passed: 0 }, true).status, "NOT_RUN");
  assert.equal(classifyGate(ok, counts, true).status, "PASS");
});
