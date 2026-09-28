import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertScheduler } from "../src/alerts.js";

afterEach(() => vi.useRealTimers());

describe("AlertScheduler", () => {
  it("evaluates on start and then every interval without overlapping runs", async () => {
    vi.useFakeTimers();
    let active = 0;
    let peak = 0;
    let calls = 0;
    const store = {
      run: async () => {
        calls++;
        active++;
        peak = Math.max(peak, active);
        await new Promise((resolve) => setTimeout(resolve, 5_000));
        active--;
        return [];
      },
    };
    const scheduler = new AlertScheduler(store, 1_000);
    scheduler.start();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls).toBeGreaterThanOrEqual(3);
    expect(peak).toBe(1);
    const stopping = scheduler.stop();
    await vi.advanceTimersByTimeAsync(5_000);
    await stopping;
    const after = calls;
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls).toBe(after);
  });

  it("keeps scheduling after a failed evaluation and reports the error", async () => {
    vi.useFakeTimers();
    const errors: unknown[] = [];
    let calls = 0;
    const store = {
      run: async () => {
        calls++;
        if (calls === 1) throw new Error("db down");
        return [];
      },
    };
    const scheduler = new AlertScheduler(store, 1_000, (error) => errors.push(error));
    scheduler.start();
    await vi.advanceTimersByTimeAsync(2_500);
    expect(errors).toHaveLength(1);
    expect(calls).toBeGreaterThanOrEqual(2);
    await scheduler.stop();
  });

  it("rejects intervals that would hammer the database", () => {
    expect(() => new AlertScheduler({ run: async () => [] }, 10)).toThrow();
  });
});
