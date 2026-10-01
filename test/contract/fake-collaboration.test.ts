import { expect, it } from "vitest";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeCollaborationPort } from "../../src/testkit/collaboration.js";

const options = { signal: new AbortController().signal, deadline: 10 };
const request = { agentId: "agent", version: "1.0.0", input: { a: 1, b: 2 }, idempotencyKey: "k" };
function fixture(status: "completed" | "failed" = "completed") {
  return createFakeCollaborationPort({
    clock: new ManualClock(),
    maxBytes: 1024,
    maxRuns: 1,
    fixtures: [
      {
        agentId: "agent",
        version: "1.0.0",
        capabilities: ["analyze"],
        output: { answer: 42 },
        status,
      },
    ],
  });
}
it("discovers granted versions, deduplicates invocation and returns isolated results", async () => {
  const port = fixture();
  expect(await port.discover({ capability: "analyze", limit: 1 }, options)).toMatchObject({
    status: "ok",
    output: [{ agentId: "agent" }],
  });
  const first = await port.invoke(request, options);
  expect(first).toMatchObject({ status: "ok", output: { runId: "fake-child-1" } });
  expect(await port.invoke({ ...request, input: { b: 2, a: 1 } }, options)).toEqual(first);
  expect(await port.invoke({ ...request, input: {} }, options)).toMatchObject({
    status: "denied",
    error: { code: "idempotency_conflict" },
  });
  expect(await port.invoke({ ...request, idempotencyKey: "next" }, options)).toMatchObject({
    status: "denied",
    error: { code: "run_limit" },
  });
  expect(await port.wait({ runIds: ["fake-child-1"] }, options)).toMatchObject({
    output: { completedRunIds: ["fake-child-1"] },
  });
  const result = await port.result({ runId: "fake-child-1" }, options);
  if (result.status === "ok") result.output.output = "tampered";
  expect(await port.result({ runId: "fake-child-1" }, options)).toMatchObject({
    output: { output: { answer: 42 } },
  });
  expect(await fixture().result({ runId: "fake-child-1" }, options)).toMatchObject({
    status: "denied",
  });
});
it("rejects expanded authority and unknown child identities", async () => {
  const port = fixture();
  expect(await port.invoke({ ...request, version: "2.0.0" }, options)).toMatchObject({
    status: "denied",
  });
  expect(
    await port.invoke({ ...request, workspaceId: "other" } as typeof request, options),
  ).toMatchObject({ status: "denied" });
  expect(await port.wait({ runIds: ["other"] }, options)).toMatchObject({ status: "denied" });
  expect(await port.invoke({ ...request, input: "é".repeat(1024) }, options)).toMatchObject({
    status: "denied",
  });
});
it("does not allocate children on cancellation or an elapsed deadline", async () => {
  const port = fixture();
  const controller = new AbortController();
  controller.abort();
  expect(await port.invoke(request, { ...options, signal: controller.signal })).toMatchObject({
    status: "failed",
  });
  expect(await port.invoke(request, { ...options, deadline: 0 })).toMatchObject({
    status: "failed",
  });
  expect(await port.invoke(request, options)).toMatchObject({
    status: "ok",
    output: { runId: "fake-child-1" },
  });
});
it("does not present failed children as completed or expose their output", async () => {
  const port = fixture("failed");
  await port.invoke(request, options);
  expect(await port.wait({ runIds: ["fake-child-1"] }, options)).toMatchObject({
    output: { completedRunIds: [] },
  });
  const result = await port.result({ runId: "fake-child-1" }, options);
  expect(result).toMatchObject({ output: { status: "failed" } });
  if (result.status === "ok") expect(result.output).not.toHaveProperty("output");
});

it("reserves child capacity across concurrent calls and bounds replay waiting independently", async () => {
  const clock = new ManualClock();
  let release!: () => void;
  let calls = 0;
  const port = createFakeCollaborationPort({
    fixtures: [
      {
        agentId: "agent",
        version: "1.0.0",
        capabilities: ["analyze"],
        output: null,
        status: "completed",
      },
    ],
    clock,
    maxBytes: 1024,
    maxRuns: 1,
    before: async (operation) => {
      if (operation !== "invoke") return;
      calls++;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    },
  });
  const original = port.invoke(request, { ...options, deadline: 100 });
  const replay = port.invoke(request, options);
  expect(await port.invoke({ ...request, idempotencyKey: "other" }, options)).toMatchObject({
    status: "denied",
    error: { code: "run_limit" },
  });
  clock.advance(10);
  expect(await replay).toMatchObject({ status: "unknown" });
  release();
  expect(await original).toMatchObject({ status: "ok", output: { runId: "fake-child-1" } });
  expect(calls).toBe(1);
  expect(clock.pendingTimers).toBe(0);
});

it("retains an unknown child invocation after timeout and ignores late completion", async () => {
  const clock = new ManualClock();
  let release!: () => void;
  let received!: AbortSignal;
  let calls = 0;
  const port = createFakeCollaborationPort({
    fixtures: [
      { agentId: "agent", version: "1.0.0", capabilities: [], output: null, status: "completed" },
    ],
    clock,
    maxBytes: 1024,
    maxRuns: 1,
    before: async (operation, signal) => {
      if (operation !== "invoke") return;
      calls++;
      received = signal;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    },
  });
  const pending = port.invoke(request, options);
  clock.advance(10);
  expect(await pending).toMatchObject({
    status: "unknown",
    error: { code: "deadline_after_dispatch" },
  });
  expect(received.aborted).toBe(true);
  release();
  expect(await port.invoke(request, { ...options, deadline: 100 })).toMatchObject({
    status: "unknown",
  });
  expect(await port.result({ runId: "fake-child-1" }, { ...options, deadline: 100 })).toMatchObject(
    { status: "denied" },
  );
  expect(calls).toBe(1);
  expect(clock.pendingTimers).toBe(0);
});
