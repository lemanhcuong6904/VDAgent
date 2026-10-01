import { expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/index.js";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeToolPort, type FakeTool } from "../../src/testkit/tools.js";

const scope: AgentScope = {
  tenantId: "t",
  workspaceId: "w",
  actorId: "a",
  audience: "internal",
  taskId: "task",
  runId: "r",
  attemptId: "attempt",
  agentId: "agent",
  agentVersion: "1.0.0",
  policyRevision: "p",
  fence: "1",
  traceId: "trace",
};
function fixture(execute: FakeTool["execute"]) {
  const clock = new ManualClock();
  const port = createFakeToolPort({
    scope,
    grants: ["write"],
    tools: new Map([["write", { effect: "write", execute }]]),
    clock,
    maxInputBytes: 64,
    maxOutputBytes: 64,
    maxExecutions: 2,
  });
  return { port, clock, options: { signal: new AbortController().signal, deadline: 10 } };
}
it("deduplicates concurrent effects and keeps replay responses isolated", async () => {
  let calls = 0;
  const { port, options } = fixture(async (_input, received) => {
    calls++;
    expect(received.workspaceId).toBe("w");
    expect(Object.isFrozen(received)).toBe(true);
    return { count: calls };
  });
  const request = { toolId: "write", input: null, idempotencyKey: "k" };
  const [a, b] = await Promise.all([port.invoke(request, options), port.invoke(request, options)]);
  expect(calls).toBe(1);
  expect(a).toEqual(b);
  expect(a).not.toBe(b);
  expect(await port.invoke({ ...request, input: 2 }, options)).toMatchObject({
    status: "denied",
    error: { code: "idempotency_conflict" },
  });
});
it("denies ungranted, oversized and forged-scope requests before side effects", async () => {
  let calls = 0;
  const { port, options } = fixture(async () => ++calls);
  const request = { toolId: "write", input: null, idempotencyKey: "k" };
  expect(await port.invoke({ ...request, toolId: "shell" }, options)).toMatchObject({
    status: "denied",
  });
  expect(await port.invoke({ ...request, input: "x".repeat(65) }, options)).toMatchObject({
    status: "denied",
  });
  expect(
    await port.invoke({ ...request, workspaceId: "other" } as typeof request, options),
  ).toMatchObject({ status: "denied" });
  expect(calls).toBe(0);
});
it("retains unknown outcomes on replay instead of retrying timed-out writes", async () => {
  let calls = 0;
  const { port, options, clock } = fixture(async () => {
    calls++;
    return new Promise(() => {});
  });
  const request = { toolId: "write", input: null, idempotencyKey: "k" };
  const first = port.invoke(request, options);
  clock.advance(10);
  expect(await first).toMatchObject({ status: "unknown" });
  expect(await port.invoke(request, { ...options, deadline: 20 })).toMatchObject({
    status: "unknown",
  });
  expect(calls).toBe(1);
});
