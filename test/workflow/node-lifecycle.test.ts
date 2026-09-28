import { beforeEach, describe, expect, it } from "vitest";
import {
  type NodeLifecycleListener,
  NodeLifecycleManager,
} from "../../src/workflow/node-lifecycle.js";
import type { WorkflowError } from "../../src/workflow/workflow-module.js";

describe("NodeLifecycleManager", () => {
  let manager: NodeLifecycleManager;

  beforeEach(() => {
    manager = new NodeLifecycleManager();
  });

  describe("start", () => {
    it("should start a node execution", async () => {
      const execution = await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: { message: "test" },
      });

      expect(execution.nodeId).toBe("node-1");
      expect(execution.runId).toBe("run-1");
      expect(execution.attemptId).toBe("attempt-1");
      expect(execution.status).toBe("running");
      expect(execution.input).toEqual({ message: "test" });
      expect(execution.attempts).toHaveLength(1);
      expect(execution.attempts[0].status).toBe("running");
    });

    it("should reject starting a node that is already running", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await expect(
        manager.start({
          nodeId: "node-1",
          runId: "run-1",
          attemptId: "attempt-2",
          input: {},
        }),
      ).rejects.toThrow("already running");
    });
  });

  describe("checkpoint", () => {
    it("should create a checkpoint", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      const checkpoint = await manager.checkpoint({
        nodeId: "node-1",
        runId: "run-1",
        state: { progress: 50 },
      });

      expect(checkpoint.id).toBeDefined();
      expect(checkpoint.nodeId).toBe("node-1");
      expect(checkpoint.state).toEqual({ progress: 50 });
      expect(checkpoint.stateHash).toBeDefined();

      const execution = manager.getExecution("run-1", "node-1");
      expect(execution?.status).toBe("checkpoint");
      expect(execution?.checkpoints).toHaveLength(1);
    });

    it("should reject checkpoint for non-existent node", async () => {
      await expect(
        manager.checkpoint({
          nodeId: "node-999",
          runId: "run-1",
          state: {},
        }),
      ).rejects.toThrow("not found");
    });

    it("should reject checkpoint for completed node", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.complete({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        output: {},
        usage: { durationMs: 100 },
      });

      await expect(
        manager.checkpoint({
          nodeId: "node-1",
          runId: "run-1",
          state: {},
        }),
      ).rejects.toThrow("Cannot checkpoint");
    });
  });

  describe("wait", () => {
    it("should put node in waiting state", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.wait({
        nodeId: "node-1",
        runId: "run-1",
        reason: "approval",
        message: "Waiting for approval",
        timeoutMs: 60000,
      });

      const execution = manager.getExecution("run-1", "node-1");
      expect(execution?.status).toBe("waiting");
      expect(execution?.metadata?.waitReason).toBe("approval");
      expect(execution?.metadata?.waitMessage).toBe("Waiting for approval");
    });
  });

  describe("resume", () => {
    it("should resume a waiting node", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.wait({
        nodeId: "node-1",
        runId: "run-1",
        reason: "approval",
        message: "Waiting for approval",
      });

      const resumed = await manager.resume({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-2",
      });

      expect(resumed.status).toBe("running");
      expect(resumed.attemptId).toBe("attempt-2");
      expect(resumed.attempts).toHaveLength(2);
      expect(resumed.metadata?.waitReason).toBeUndefined();
    });

    it("should resume with new input", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: { old: "data" },
      });

      await manager.wait({
        nodeId: "node-1",
        runId: "run-1",
        reason: "input",
        message: "Waiting for input",
      });

      const resumed = await manager.resume({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-2",
        input: { new: "data" },
      });

      expect(resumed.input).toEqual({ new: "data" });
    });

    it("should reject resume for running node", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await expect(
        manager.resume({
          nodeId: "node-1",
          runId: "run-1",
          attemptId: "attempt-2",
        }),
      ).rejects.toThrow("Cannot resume");
    });
  });

  describe("complete", () => {
    it("should complete a node successfully", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      const completed = await manager.complete({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        output: { result: "success" },
        usage: { durationMs: 1500, costUsd: 0.001 },
      });

      expect(completed.status).toBe("completed");
      expect(completed.output).toEqual({ result: "success" });
      expect(completed.completedAt).toBeDefined();
      expect(completed.attempts[0].status).toBe("completed");
      expect(completed.attempts[0].durationMs).toBe(1500);
    });

    it("should reject completion with wrong attempt ID", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await expect(
        manager.complete({
          nodeId: "node-1",
          runId: "run-1",
          attemptId: "attempt-2",
          output: {},
          usage: { durationMs: 100 },
        }),
      ).rejects.toThrow("Attempt ID mismatch");
    });
  });

  describe("fail", () => {
    it("should mark a node as failed", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      const error: WorkflowError = {
        code: "execution_error",
        message: "Something went wrong",
        retryable: true,
      };

      const failed = await manager.fail({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        error,
        usage: { durationMs: 500 },
      });

      expect(failed.status).toBe("failed");
      expect(failed.error).toEqual(error);
      expect(failed.completedAt).toBeDefined();
      expect(failed.attempts[0].status).toBe("failed");
      expect(failed.attempts[0].error).toEqual(error);
    });
  });

  describe("cancel", () => {
    it("should cancel a running node", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      const cancelled = await manager.cancel({
        nodeId: "node-1",
        runId: "run-1",
        reason: "User requested cancellation",
      });

      expect(cancelled.status).toBe("cancelled");
      expect(cancelled.metadata?.cancelReason).toBe("User requested cancellation");
      expect(cancelled.attempts[0].status).toBe("cancelled");
    });

    it("should cancel a waiting node", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.wait({
        nodeId: "node-1",
        runId: "run-1",
        reason: "approval",
        message: "Waiting",
      });

      const cancelled = await manager.cancel({
        nodeId: "node-1",
        runId: "run-1",
        reason: "Timeout",
      });

      expect(cancelled.status).toBe("cancelled");
    });

    it("should reject cancelling a completed node", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.complete({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        output: {},
        usage: { durationMs: 100 },
      });

      await expect(
        manager.cancel({
          nodeId: "node-1",
          runId: "run-1",
          reason: "Test",
        }),
      ).rejects.toThrow("Cannot cancel");
    });
  });

  describe("replan", () => {
    it("should mark node for replanning", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.replan({
        nodeId: "node-1",
        runId: "run-1",
        reason: "Dependencies changed",
        newPlanRequired: true,
      });

      const execution = manager.getExecution("run-1", "node-1");
      expect(execution?.status).toBe("replanning");
      expect(execution?.metadata?.replanReason).toBe("Dependencies changed");
      expect(execution?.metadata?.replanRequired).toBe(true);
    });
  });

  describe("getExecution", () => {
    it("should get node execution", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: { test: "data" },
      });

      const execution = manager.getExecution("run-1", "node-1");
      expect(execution).toBeDefined();
      expect(execution?.nodeId).toBe("node-1");
      expect(execution?.input).toEqual({ test: "data" });
    });

    it("should return undefined for non-existent execution", () => {
      const execution = manager.getExecution("run-999", "node-999");
      expect(execution).toBeUndefined();
    });
  });

  describe("getRunExecutions", () => {
    it("should get all executions for a run", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.start({
        nodeId: "node-2",
        runId: "run-1",
        attemptId: "attempt-2",
        input: {},
      });

      await manager.start({
        nodeId: "node-3",
        runId: "run-2",
        attemptId: "attempt-3",
        input: {},
      });

      const run1Executions = manager.getRunExecutions("run-1");
      expect(run1Executions).toHaveLength(2);
      expect(run1Executions.map((e) => e.nodeId)).toContain("node-1");
      expect(run1Executions.map((e) => e.nodeId)).toContain("node-2");

      const run2Executions = manager.getRunExecutions("run-2");
      expect(run2Executions).toHaveLength(1);
    });
  });

  describe("getRunStatistics", () => {
    it("should compute statistics for a run", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.start({
        nodeId: "node-2",
        runId: "run-1",
        attemptId: "attempt-2",
        input: {},
      });

      await manager.complete({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        output: {},
        usage: { durationMs: 100 },
      });

      await manager.fail({
        nodeId: "node-2",
        runId: "run-1",
        attemptId: "attempt-2",
        error: { code: "test_error", message: "Test", retryable: false },
        usage: { durationMs: 50 },
      });

      const stats = manager.getRunStatistics("run-1");
      expect(stats.total).toBe(2);
      expect(stats.completed).toBe(1);
      expect(stats.failed).toBe(1);
      expect(stats.running).toBe(0);
      expect(stats.totalAttempts).toBe(2);
    });

    it("should track checkpoints in statistics", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.checkpoint({
        nodeId: "node-1",
        runId: "run-1",
        state: { step: 1 },
      });

      await manager.checkpoint({
        nodeId: "node-1",
        runId: "run-1",
        state: { step: 2 },
      });

      const stats = manager.getRunStatistics("run-1");
      expect(stats.totalCheckpoints).toBe(2);
      expect(stats.checkpoint).toBe(1);
    });
  });

  describe("event listeners", () => {
    it("should notify listeners of events", async () => {
      const events: string[] = [];
      const listener: NodeLifecycleListener = {
        runId: "run-1",
        onEvent: async (event, _execution) => {
          events.push(event);
        },
      };

      manager.subscribe(listener);

      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.complete({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        output: {},
        usage: { durationMs: 100 },
      });

      expect(events).toContain("node.started");
      expect(events).toContain("node.completed");
    });

    it("should support global listeners", async () => {
      const events: Array<{ event: string; runId: string }> = [];
      const listener: NodeLifecycleListener = {
        onEvent: async (event, execution) => {
          events.push({ event, runId: execution.runId });
        },
      };

      manager.subscribe(listener);

      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.start({
        nodeId: "node-2",
        runId: "run-2",
        attemptId: "attempt-2",
        input: {},
      });

      expect(events).toHaveLength(2);
      expect(events.map((e) => e.runId)).toContain("run-1");
      expect(events.map((e) => e.runId)).toContain("run-2");
    });

    it("should support unsubscribe", async () => {
      const events: string[] = [];
      const listener: NodeLifecycleListener = {
        runId: "run-1",
        onEvent: async (event) => {
          events.push(event);
        },
      };

      const unsubscribe = manager.subscribe(listener);

      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      expect(events).toHaveLength(1);

      unsubscribe();

      await manager.start({
        nodeId: "node-2",
        runId: "run-1",
        attemptId: "attempt-2",
        input: {},
      });

      expect(events).toHaveLength(1);
    });
  });

  describe("clearRun", () => {
    it("should clear all executions for a run", async () => {
      await manager.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: {},
      });

      await manager.start({
        nodeId: "node-2",
        runId: "run-1",
        attemptId: "attempt-2",
        input: {},
      });

      await manager.start({
        nodeId: "node-3",
        runId: "run-2",
        attemptId: "attempt-3",
        input: {},
      });

      manager.clearRun("run-1");

      expect(manager.getRunExecutions("run-1")).toHaveLength(0);
      expect(manager.getRunExecutions("run-2")).toHaveLength(1);
    });
  });
});
