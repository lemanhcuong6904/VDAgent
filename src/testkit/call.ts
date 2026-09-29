import type { CallOptions, PortOutcome } from "../contracts/index.js";
import { encodeBoundedJson } from "./json.js";

export interface TestClock {
  now(): number;
  schedule(delayMs: number, callback: () => void): () => void;
}
/** Explicit clock injection keeps fault/concurrency tests independent of wall time. */
export class ManualClock implements TestClock {
  private time: number;
  private sequence = 0;
  private readonly timers = new Map<number, { at: number; callback: () => void }>();
  constructor(start = 0) {
    if (!Number.isFinite(start)) throw new Error("Invalid clock origin");
    this.time = start;
  }
  now(): number {
    return this.time;
  }
  schedule(delayMs: number, callback: () => void): () => void {
    if (!Number.isFinite(delayMs) || delayMs < 0) throw new Error("Invalid clock delay");
    const id = ++this.sequence;
    this.timers.set(id, { at: this.time + delayMs, callback });
    return () => {
      this.timers.delete(id);
    };
  }
  advance(milliseconds: number): void {
    if (!Number.isFinite(milliseconds) || milliseconds < 0) throw new Error("Clock cannot reverse");
    const end = this.time + milliseconds;
    while (true) {
      const next = [...this.timers.entries()]
        .filter(([, timer]) => timer.at <= end)
        .sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
      if (!next) break;
      this.time = next[1].at;
      this.timers.delete(next[0]);
      next[1].callback();
    }
    this.time = end;
  }
  get pendingTimers(): number {
    return this.timers.size;
  }
}

export function runFakeCall<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  options: CallOptions,
  limits: { maxOutputBytes: number; correlationId: string; effect: "read" | "write" },
  clock: TestClock,
): Promise<PortOutcome<T>> {
  const failure = (code: string, unknown = false): PortOutcome<T> => {
    const error = {
      code,
      retryable: false as const,
      safeMessage: code,
      correlationId: limits.correlationId,
    };
    return unknown
      ? { status: "unknown", error: { ...error, class: "unknown" }, evidence: [] }
      : { status: "failed", error: { ...error, class: "validation" }, evidence: [] };
  };
  if (
    !Number.isFinite(options.deadline) ||
    !Number.isSafeInteger(limits.maxOutputBytes) ||
    limits.maxOutputBytes < 1
  )
    return Promise.resolve(failure("invalid_call_limits"));
  if (options.signal.aborted) return Promise.resolve(failure("cancelled_before_dispatch"));
  if (options.deadline <= clock.now()) return Promise.resolve(failure("deadline_before_dispatch"));
  return new Promise((resolve) => {
    const controller = new AbortController();
    let done = false;
    let cancelTimer = () => {};
    const finish = (outcome: PortOutcome<T>) => {
      if (done) return;
      done = true;
      cancelTimer();
      options.signal.removeEventListener("abort", abort);
      resolve(outcome);
    };
    const interrupt = (code: string) => {
      // Resolve unknown before signaling a potentially effectful operation.
      finish(failure(code, limits.effect === "write"));
      controller.abort();
    };
    const abort = () => interrupt("cancelled_after_dispatch");
    options.signal.addEventListener("abort", abort, { once: true });
    cancelTimer = clock.schedule(options.deadline - clock.now(), () =>
      interrupt("deadline_after_dispatch"),
    );
    let pending: Promise<T>;
    try {
      pending = operation(controller.signal);
    } catch {
      finish(failure("operation_failed", limits.effect === "write"));
      return;
    }
    pending.then(
      (output) => {
        if (done) return;
        try {
          const encoded = encodeBoundedJson(output, limits.maxOutputBytes);
          if (
            encoded === undefined ||
            new TextEncoder().encode(encoded).byteLength > limits.maxOutputBytes
          ) {
            finish(failure("output_limit", limits.effect === "write"));
          } else
            finish({
              status: "ok",
              output: JSON.parse(encoded) as T,
              evidence: [],
              limitations: ["Deterministic test double; not verified external evidence"],
            });
        } catch (error) {
          finish(
            failure(
              error instanceof Error && error.message === "json_byte_limit"
                ? "output_limit"
                : "invalid_output",
              limits.effect === "write",
            ),
          );
        }
      },
      () => finish(failure("operation_failed", limits.effect === "write")),
    );
  });
}

/** A duplicate caller can stop waiting without cancelling or re-dispatching the original effect. */
export async function awaitFakeReplay<T>(
  pending: Promise<PortOutcome<T>>,
  options: CallOptions,
  limits: { correlationId: string; effect: "read" | "write" },
  clock: TestClock,
): Promise<PortOutcome<T>> {
  let outcome: PortOutcome<T> | undefined;
  const waiting = await runFakeCall(
    async () => {
      outcome = await pending;
      return null;
    },
    options,
    { ...limits, maxOutputBytes: 4 },
    clock,
  );
  if (waiting.status === "ok") {
    if (!outcome) throw new Error("Replay resolved without outcome");
    return structuredClone(outcome);
  }
  return waiting;
}
