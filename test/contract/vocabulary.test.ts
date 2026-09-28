import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import {
  AgentScopeSchema,
  ArtifactRefSchema,
  type StructuredError,
  StructuredErrorSchema,
  UsageSummarySchema,
} from "../../src/contracts/index.js";

const ajv = new Ajv2020({ strict: true });
describe("public v1 vocabulary", () => {
  it("requires hash/length only for ready artifacts and keeps unknown distinct", () => {
    const validate = ajv.compile(ArtifactRefSchema);
    const ref = { id: "a", workspaceId: "w", ownerRunId: "r", kind: "report", version: "1" };
    expect(validate({ ...ref, status: "unknown" })).toBe(true);
    expect(validate({ ...ref, status: "ready" })).toBe(false);
    expect(validate({ ...ref, status: "ready", sha256: "a".repeat(64), bytes: 0 })).toBe(true);
    expect(validate({ ...ref, status: "unknown", sha256: "a".repeat(64), bytes: 0 })).toBe(false);
  });
  it("preserves classified unknown errors and rejects unknown fields and oversized text", () => {
    const validate = ajv.compile(StructuredErrorSchema);
    const error: StructuredError = {
      code: "effect_unknown",
      class: "unknown",
      retryable: false,
      safeMessage: "Reconciliation required",
      correlationId: "trace-1",
    };
    expect(validate(error)).toBe(true);
    expect(validate({ ...error, class: "success" })).toBe(false);
    expect(validate({ ...error, providerSecret: "not allowed" })).toBe(false);
    expect(validate({ ...error, safeMessage: "x".repeat(2049) })).toBe(false);
  });
  it("requires complete server-owned identity and a string fence without numeric precision loss", () => {
    const validate = ajv.compile(AgentScopeSchema);
    const scope = {
      tenantId: "t",
      workspaceId: "w",
      actorId: "a",
      audience: "internal",
      taskId: "task",
      runId: "run",
      attemptId: "attempt",
      agentId: "agent",
      agentVersion: "1.0.0",
      policyRevision: "p1",
      fence: "9007199254740992",
      traceId: "trace",
    };
    expect(validate(scope)).toBe(true);
    expect(validate({ ...scope, tenantId: undefined })).toBe(false);
    expect(validate({ ...scope, fence: 1 })).toBe(false);
    expect(validate({ ...scope, fence: "0" })).toBe(false);
  });
  it("bounds usage and rejects negative/non-integral token counts", () => {
    const validate = ajv.compile(UsageSummarySchema);
    const usage = {
      inputTokens: 1,
      outputTokens: 2,
      cacheReadTokens: 0,
      cacheWriteTokens: 0,
      modelCalls: 1,
      toolCalls: 0,
      durationMs: 10,
      estimatedCostUsd: 0.01,
    };
    expect(validate(usage)).toBe(true);
    expect(validate({ ...usage, inputTokens: -1 })).toBe(false);
    expect(validate({ ...usage, outputTokens: 1.5 })).toBe(false);
    expect(validate({ ...usage, estimatedCostUsd: Infinity })).toBe(false);
  });
});
