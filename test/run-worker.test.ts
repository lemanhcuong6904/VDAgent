import { describe, expect, it, vi } from "vitest";
import { DurableRunWorker, RetryableRunError } from "../src/run-worker.js";

function claimedRun() {
  return {
    id: "run-1",
    space_id: "space-1",
    user_id: "user-1",
    workflow_id: "workflow",
    workflow_version: "1.0.0",
    status: "queued" as const,
    input: {},
    attempt: 1,
    fencing_token: "7",
    lease_until: new Date(Date.now() + 30_000),
  };
}

describe("durable run worker", () => {
  it("claims, executes and completes a run with the fencing token", async () => {
    const calls: string[] = [];
    const ledger = {
      async claim() {
        calls.push("claim");
        return claimedRun();
      },
      async heartbeat() {
        calls.push("heartbeat");
        return true;
      },
      async transition(_id: string, _worker: string, token: string, from: string, to: string) {
        calls.push(`${token}:${from}->${to}`);
        return true;
      },
    } as never;
    const executor = { execute: vi.fn(async () => ({ ok: true })) };
    const worker = new DurableRunWorker(ledger, executor, { workerId: "worker-1" });

    await expect(worker.runOnce()).resolves.toBe(true);
    expect(calls).toEqual(["claim", "7:leased->running", "7:running->completed"]);
    expect(executor.execute).toHaveBeenCalledOnce();
  });

  it("marks retryable failures without swallowing the fencing contract", async () => {
    const transitions: string[] = [];
    const ledger = {
      async claim() {
        return claimedRun();
      },
      async heartbeat() {
        return true;
      },
      async transition(_id: string, _worker: string, _token: string, from: string, to: string) {
        transitions.push(`${from}->${to}`);
        return true;
      },
    } as never;
    const worker = new DurableRunWorker(
      ledger,
      {
        execute: async () => {
          throw new RetryableRunError("provider busy");
        },
      },
      { workerId: "worker-1" },
    );

    await expect(worker.runOnce()).resolves.toBe(true);
    expect(transitions).toEqual(["leased->running", "running->retryable"]);
  });

  it("does not convert a cancellation request into a failed run", async () => {
    const transitions: string[] = [];
    const ledger = {
      async claim() {
        return claimedRun();
      },
      async heartbeat() {
        return false;
      },
      async isCancellationRequested() {
        return true;
      },
      async transition(_id: string, _worker: string, _token: string, from: string, to: string) {
        transitions.push(`${from}->${to}`);
        return true;
      },
    } as never;
    const worker = new DurableRunWorker(
      ledger,
      {
        execute: async (_run, signal) => {
          await new Promise<void>((resolve) => {
            signal.addEventListener("abort", () => resolve(), { once: true });
          });
          throw signal.reason;
        },
      },
      { workerId: "worker-1", leaseMs: 1_000 },
    );

    const result = await worker.runOnce();
    expect(result).toBe(true);
    expect(transitions).toContain("running->cancelled");
  });
});
