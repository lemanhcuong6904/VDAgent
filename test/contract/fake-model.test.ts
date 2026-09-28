import { expect, it } from "vitest";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeModelPort } from "../../src/testkit/model.js";

const request = {
  profile: "fixture",
  prompt: "hello",
  outputSchema: { type: "string" },
  contextRefs: [],
  idempotencyKey: "k",
};
const options = () => ({ signal: new AbortController().signal, deadline: 100 });
it("retains timeout on replay and rejects new calls after the reserved budget", async () => {
  const clock = new ManualClock();
  let calls = 0;
  let received!: AbortSignal;
  let complete!: (value: string) => void;
  const port = createFakeModelPort({
    profiles: ["fixture"],
    clock,
    maxInputBytes: 4096,
    maxOutputBytes: 128,
    maxCalls: 1,
    respond: async (_input, signal) => {
      calls++;
      received = signal;
      return new Promise<string>((resolve) => {
        complete = resolve;
      });
    },
  });
  const pending = port.complete(request, options());
  clock.advance(100);
  expect(await pending).toMatchObject({
    status: "failed",
    error: { code: "deadline_after_dispatch" },
  });
  expect(received.aborted).toBe(true);
  complete("late");
  expect(await port.complete(request, { ...options(), deadline: 200 })).toMatchObject({
    status: "failed",
    error: { code: "deadline_after_dispatch" },
  });
  expect(
    await port.complete({ ...request, idempotencyKey: "new" }, { ...options(), deadline: 200 }),
  ).toMatchObject({ status: "denied", error: { code: "model_call_limit" } });
  expect(calls).toBe(1);
  expect(clock.pendingTimers).toBe(0);
});

it("rejects cancellation before dispatch without consuming the call budget", async () => {
  let calls = 0;
  const port = createFakeModelPort({
    profiles: ["fixture"],
    clock: new ManualClock(),
    maxInputBytes: 4096,
    maxOutputBytes: 128,
    maxCalls: 1,
    respond: async () => {
      calls++;
      return "ok";
    },
  });
  const controller = new AbortController();
  controller.abort();
  expect(await port.complete(request, { ...options(), signal: controller.signal })).toMatchObject({
    status: "failed",
  });
  expect(await port.complete(request, options())).toMatchObject({ status: "ok" });
  expect(calls).toBe(1);
});

it("rejects oversized output and keeps fixture exceptions out of safe errors", async () => {
  const make = (respond: () => Promise<string>) =>
    createFakeModelPort({
      profiles: ["fixture"],
      clock: new ManualClock(),
      maxInputBytes: 4096,
      maxOutputBytes: 8,
      maxCalls: 1,
      respond,
    });
  expect(await make(async () => "😀😀").complete(request, options())).toMatchObject({
    status: "failed",
    error: { code: "output_limit" },
  });
  const result = await make(async () => {
    throw new Error("private provider content");
  }).complete(request, options());
  expect(result).toMatchObject({ status: "failed", error: { safeMessage: "operation_failed" } });
  expect(JSON.stringify(result)).not.toContain("private provider");
});
it("validates structured output and replays deterministic provider identity", async () => {
  let calls = 0;
  const port = createFakeModelPort({
    profiles: ["fixture"],
    clock: new ManualClock(),
    maxInputBytes: 4096,
    maxOutputBytes: 128,
    maxCalls: 2,
    respond: async () => {
      calls++;
      return "answer";
    },
  });
  const [first, second] = await Promise.all([
    port.complete(request, options()),
    port.complete(request, options()),
  ]);
  expect(first).toEqual(second);
  expect(first).toMatchObject({
    status: "ok",
    output: { output: "answer", providerRequestId: "fake-model-1" },
  });
  expect(calls).toBe(1);
  expect(await port.complete({ ...request, prompt: "changed" }, options())).toMatchObject({
    status: "failed",
    error: { code: "idempotency_conflict" },
  });
});
it("denies profiles and remote schemas before calling the fixture", async () => {
  let calls = 0;
  const port = createFakeModelPort({
    profiles: ["fixture"],
    clock: new ManualClock(),
    maxInputBytes: 4096,
    maxOutputBytes: 128,
    maxCalls: 1,
    respond: async () => ++calls,
  });
  expect(await port.complete({ ...request, profile: "unrestricted" }, options())).toMatchObject({
    status: "denied",
  });
  expect(
    await port.complete(
      { ...request, outputSchema: { $ref: "https://example.invalid/schema" } },
      options(),
    ),
  ).toMatchObject({ status: "failed" });
  expect(calls).toBe(0);
  expect(await port.complete(request, options())).toMatchObject({
    status: "failed",
    error: { code: "model_output_schema" },
  });
});

it("lets a replay caller time out without cancelling the original model call", async () => {
  const clock = new ManualClock();
  let release!: (value: string) => void;
  let received!: AbortSignal;
  let calls = 0;
  const port = createFakeModelPort({
    profiles: ["fixture"],
    clock,
    maxInputBytes: 4096,
    maxOutputBytes: 64,
    maxCalls: 1,
    respond: async (_input, signal) => {
      calls++;
      received = signal;
      return new Promise<string>((resolve) => {
        release = resolve;
      });
    },
  });
  const original = port.complete(request, options());
  const replay = port.complete(request, { ...options(), deadline: 10 });
  clock.advance(10);
  expect(await replay).toMatchObject({
    status: "failed",
    error: { code: "deadline_after_dispatch" },
  });
  expect(received.aborted).toBe(false);
  release("original output");
  expect(await original).toMatchObject({ status: "ok", output: { output: "original output" } });
  expect(await port.complete(request, options())).toMatchObject({ status: "ok" });
  expect(calls).toBe(1);
  expect(clock.pendingTimers).toBe(0);
});
