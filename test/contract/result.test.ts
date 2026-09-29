import { Ajv2020 } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import { expect, it } from "vitest";
import { AgentResultWireSchema } from "../../src/contracts/index.js";

const ajv = new Ajv2020({ strict: true });
ajv.addFormat("date-time", fullFormats["date-time"]);
const validate = ajv.compile(AgentResultWireSchema);
const base = {
  artifacts: [],
  evidence: [],
  warnings: [],
  usage: {
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
    modelCalls: 0,
    toolCalls: 0,
    durationMs: 0,
    estimatedCostUsd: 0,
  },
};
it("validates nested JSON output while rejecting incomplete or contradictory outcomes", () => {
  expect(
    validate({ ...base, status: "completed", output: { nested: [1, null, true, { text: "ok" }] } }),
  ).toBe(true);
  expect(validate({ ...base, status: "completed" })).toBe(false);
  expect(validate({ ...base, status: "completed", output: NaN })).toBe(false);
  const wait = {
    reason: "tool",
    executionId: "e",
    idempotencyKey: "k",
    expiresAt: "2026-09-26T00:00:00Z",
  };
  expect(validate({ ...base, status: "waiting", wait })).toBe(true);
  expect(validate({ ...base, status: "waiting", wait, output: "done" })).toBe(false);
  expect(validate({ ...base, status: "needs_approval", wait })).toBe(false);
});
it("bounds domain dictionaries and result metadata without permitting extra control fields", () => {
  expect(validate({ ...base, status: "completed", output: { ["x".repeat(257)]: 1 } })).toBe(false);
  expect(
    validate({ ...base, status: "completed", output: null, warnings: Array(65).fill("w") }),
  ).toBe(false);
  expect(validate({ ...base, status: "completed", output: null, authorized: true })).toBe(false);
});
