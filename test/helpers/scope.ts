import type { AgentScope } from "../../src/contracts/index.js";

/** Canonical AgentScope for tests; every default satisfies schemas/agent-scope.schema.json. */
export function testScope(overrides: Partial<AgentScope> = {}): AgentScope {
  return {
    tenantId: "tenant-1",
    workspaceId: "ws-1",
    actorId: "user-1",
    audience: "internal",
    taskId: "task-1",
    runId: "run-1",
    attemptId: "attempt-1",
    agentId: "agent-1",
    agentVersion: "1.0.0",
    policyRevision: "policy-1",
    fence: "1",
    traceId: "trace-1",
    ...overrides,
  };
}
