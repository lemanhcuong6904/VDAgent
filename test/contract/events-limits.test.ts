import { Ajv2020 } from "ajv/dist/2020.js";
import { expect, it } from "vitest";
import { AgentEventSchema, ExecutionLimitsSchema } from "../../src/contracts/index.js";

const ajv = new Ajv2020({ strict: true });
it("agent events cannot claim terminal authority or add unbounded metadata", () => {
  const validate = ajv.compile(AgentEventSchema);
  const event = {
    version: "agent-event.v1",
    id: "e1",
    sequence: 1,
    type: "progress",
    safeMessage: "Working",
    evidence: [],
  };
  expect(validate(event)).toBe(true);
  expect(validate({ ...event, type: "completed" })).toBe(false);
  expect(validate({ ...event, sequence: 0 })).toBe(false);
  expect(validate({ ...event, safeMessage: "x".repeat(2049) })).toBe(false);
  expect(validate({ ...event, prompt: "private content" })).toBe(false);
});
it("execution budgets distinguish disabled effects from invalid payload/deadline limits", () => {
  const validate = ajv.compile(ExecutionLimitsSchema);
  const limits = {
    timeoutMs: 100,
    maxInputBytes: 128,
    maxOutputBytes: 128,
    maxEventBytes: 128,
    maxCheckpointBytes: 128,
    maxModelCalls: 0,
    maxToolCalls: 0,
    maxChildRuns: 0,
    maxDepth: 0,
    maxCostUsd: 0,
  };
  expect(validate(limits)).toBe(true);
  for (const change of [
    { timeoutMs: 0 },
    { maxOutputBytes: 16777217 },
    { maxDepth: 65 },
    { maxModelCalls: -1 },
    { maxCostUsd: Infinity },
  ]) {
    expect(validate({ ...limits, ...change })).toBe(false);
  }
});
