import { expect, it } from "vitest";
import type {
  AgentExecutionContext,
  AgentModule,
  AgentResult,
  UsageSummary,
} from "../../src/contracts/index.js";

const usage: UsageSummary = {
  inputTokens: 0,
  outputTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  modelCalls: 0,
  toolCalls: 0,
  durationMs: 0,
  estimatedCostUsd: 0,
};
const module: AgentModule<{ value: number }, { doubled: number }> = {
  manifest: {
    apiVersion: "agent.v1",
    id: "test.double",
    version: "1.0.0",
    displayName: "Double",
    inputSchema: { type: "object" },
    outputSchema: { type: "object" },
    capabilities: ["math.double"],
    requiredPorts: [],
    toolGrants: [],
    limits: {
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
    },
    compatibility: { minHostVersion: "1.0.0" },
  },
  async execute(context) {
    return {
      status: "completed",
      output: { doubled: context.input.value * 2 },
      artifacts: [],
      evidence: [],
      usage,
      warnings: [],
    };
  },
};
it("code-only module executes without importing or touching host services", async () => {
  const context = new Proxy(
    { input: { value: 3 } },
    {
      get(target, key) {
        if (key !== "input") throw new Error(`Unexpected host access: ${String(key)}`);
        return target.input;
      },
    },
  ) as AgentExecutionContext<{ value: number }>;
  const result = await module.execute(context);
  expect(result).toMatchObject({ status: "completed", output: { doubled: 6 } });
});

function resultTypeChecks() {
  // @ts-expect-error Completed results cannot omit output.
  const missing: AgentResult<string> = {
    status: "completed",
    artifacts: [],
    evidence: [],
    usage,
    warnings: [],
  };
  const contradictory: AgentResult<string> = {
    status: "waiting",
    // @ts-expect-error Waiting cannot also claim a completed output.
    output: "done",
    wait: {
      reason: "tool",
      executionId: "e",
      idempotencyKey: "i",
      expiresAt: "2026-09-26T00:00:00Z",
    },
    artifacts: [],
    evidence: [],
    usage,
    warnings: [],
  };
  return { missing, contradictory };
}
void resultTypeChecks;
