import { describe, expect, it } from "vitest";
import { assertRunTransition, isTerminalRunStatus } from "../src/run-state.js";

describe("durable run state machine", () => {
  it("allows lease/retry/terminal paths", () => {
    expect(() => assertRunTransition("queued", "leased")).not.toThrow();
    expect(() => assertRunTransition("running", "retryable")).not.toThrow();
    expect(() => assertRunTransition("waiting", "completed")).not.toThrow();
    expect(isTerminalRunStatus("completed")).toBe(true);
    expect(isTerminalRunStatus("running")).toBe(false);
  });

  it("rejects writes after a terminal state", () => {
    expect(() => assertRunTransition("completed", "running")).toThrow("Invalid run transition");
    expect(() => assertRunTransition("failed", "retryable")).toThrow("Invalid run transition");
  });
});
