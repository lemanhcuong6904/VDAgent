import { expect, it } from "vitest";
import { ManualClock, runFakeCall } from "../../src/testkit/call.js";

const limits = { maxOutputBytes: 16, correlationId: "test", effect: "read" as const };
it("does not silently convert non-finite numbers into JSON null", async () => {
  const clock = new ManualClock();
  const result = await runFakeCall(
    async () => Number.NaN,
    { signal: new AbortController().signal, deadline: 10 },
    limits,
    clock,
  );
  expect(result).toMatchObject({ status: "failed", error: { code: "invalid_output" } });
});
it("rejects expired or cancelled calls before dispatch", async () => {
  const clock = new ManualClock(10);
  let calls = 0;
  const operation = async () => ++calls;
  const controller = new AbortController();
  expect(
    await runFakeCall(operation, { signal: controller.signal, deadline: 10 }, limits, clock),
  ).toMatchObject({ status: "failed" });
  controller.abort();
  expect(
    await runFakeCall(operation, { signal: controller.signal, deadline: 20 }, limits, clock),
  ).toMatchObject({ status: "failed" });
  expect(calls).toBe(0);
  expect(clock.pendingTimers).toBe(0);
});
it("times out writes as unknown and ignores late completion", async () => {
  const clock = new ManualClock();
  let complete!: (value: string) => void;
  let signal!: AbortSignal;
  const pending = runFakeCall(
    (s) => {
      signal = s;
      return new Promise<string>((resolve) => {
        complete = resolve;
      });
    },
    { signal: new AbortController().signal, deadline: 10 },
    { ...limits, effect: "write" },
    clock,
  );
  clock.advance(10);
  expect(await pending).toMatchObject({ status: "unknown", error: { retryable: false } });
  expect(signal.aborted).toBe(true);
  complete("late success");
  expect(await pending).toMatchObject({ status: "unknown" });
  expect(clock.pendingTimers).toBe(0);
});
it("enforces UTF-8 byte limits and cleans timers on success and rejection", async () => {
  const clock = new ManualClock();
  const options = { signal: new AbortController().signal, deadline: 100 };
  expect(await runFakeCall(async () => "😀😀😀😀", options, limits, clock)).toMatchObject({
    status: "failed",
    error: { code: "output_limit" },
  });
  expect(
    await runFakeCall(
      async () => {
        throw new Error("secret provider detail");
      },
      options,
      limits,
      clock,
    ),
  ).toMatchObject({ status: "failed", error: { safeMessage: "operation_failed" } });
  expect(await runFakeCall(async () => "ok", options, limits, clock)).toMatchObject({
    status: "ok",
    output: "ok",
  });
  expect(clock.pendingTimers).toBe(0);
});
it("propagates cancellation to an in-flight read without waiting for its promise", async () => {
  const clock = new ManualClock();
  const controller = new AbortController();
  let received!: AbortSignal;
  const pending = runFakeCall(
    (signal) => {
      received = signal;
      return new Promise<string>(() => {});
    },
    { signal: controller.signal, deadline: 10 },
    limits,
    clock,
  );
  controller.abort();
  expect(await pending).toMatchObject({
    status: "failed",
    error: { code: "cancelled_after_dispatch" },
  });
  expect(received.aborted).toBe(true);
  expect(clock.pendingTimers).toBe(0);
});
