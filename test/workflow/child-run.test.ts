import { beforeEach, describe, expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/index.js";
import {
  type ChildRunLimits,
  ChildRunManager,
  type ChildRunResult,
  type TraceContext,
} from "../../src/workflow/child-run.js";
import { testScope } from "../helpers/scope.js";

describe("ChildRunManager", () => {
  let manager: ChildRunManager;
  let rootTrace: TraceContext;
  let limits: ChildRunLimits;
  let _scope: AgentScope;

  beforeEach(() => {
    manager = new ChildRunManager();

    rootTrace = {
      traceId: "trace-1",
      spanId: "span-root",
      depth: 0,
      rootRunId: "run-root",
      parentRunId: "run-root",
    };

    limits = {
      maxDepth: 3,
      maxFanOut: 5,
      maxBudgetUsd: 10,
      deadlineMs: 60000,
    };

    _scope = testScope({ actorId: "actor-1" });
  });

  describe("Child Run Creation", () => {
    it("should create a child run with valid limits", () => {
      const result = manager.createChildRun("run-root", rootTrace, limits, { task: "test" });

      expect(result).not.toHaveProperty("error");

      const spec = result as any;
      expect(spec.runId).toBeDefined();
      expect(spec.trace.depth).toBe(1);
      expect(spec.trace.parentRunId).toBe("run-root");
      expect(spec.trace.traceId).toBe("trace-1");
      // No host-bound scope was supplied, so none is fabricated
      expect(spec.scope).toBeUndefined();
    });

    it("should reject child run exceeding depth limit", () => {
      const deepTrace: TraceContext = {
        ...rootTrace,
        depth: 3,
      };

      const result = manager.createChildRun("run-parent", deepTrace, limits, { task: "test" });

      expect(result).toHaveProperty("error");
      expect((result as any).error).toContain("Depth limit exceeded");
    });

    it("should reject child run exceeding fan-out limit", () => {
      // Create max fan-out children
      for (let i = 0; i < limits.maxFanOut; i++) {
        const result = manager.createChildRun("run-parent", rootTrace, limits, {
          task: `test-${i}`,
        });
        expect(result).not.toHaveProperty("error");
      }

      // Try to create one more
      const result = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test-overflow",
      });

      expect(result).toHaveProperty("error");
      expect((result as any).error).toContain("Fan-out limit exceeded");
    });

    it("should create child with budget tracker", () => {
      const result = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { budgetUsd: 5 },
      );

      expect(result).not.toHaveProperty("error");

      const spec = result as any;
      expect(spec.budget).toBeDefined();
      expect(spec.budget.allocatedUsd).toBe(5);
      expect(spec.budget.consumedUsd).toBe(0);
      expect(spec.budget.remainingUsd).toBe(5);
    });

    it("should create child with deadline tracker", () => {
      const result = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { deadlineMs: 30000 },
      );

      expect(result).not.toHaveProperty("error");

      const spec = result as any;
      expect(spec.deadline).toBeDefined();
      expect(spec.deadline.deadlineAt).toBeDefined();
      expect(spec.deadline.remainingMs).toBe(30000);
      expect(spec.deadline.expired).toBe(false);
    });

    it("should create child with custom scope and metadata", () => {
      const customScope = testScope({ tenantId: "tenant-2", actorId: "actor-2" });

      const result = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        {
          scope: customScope,
          metadata: { source: "api" },
        },
      );

      expect(result).not.toHaveProperty("error");

      const spec = result as any;
      expect(spec.scope).toEqual(customScope);
      expect(spec.metadata).toEqual({ source: "api" });
    });

    it("should generate unique IDs for each child", () => {
      const result1 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test1",
      }) as any;

      const result2 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test2",
      }) as any;

      expect(result1.runId).not.toBe(result2.runId);
      expect(result1.trace.spanId).not.toBe(result2.trace.spanId);
    });
  });

  describe("Result Recording", () => {
    it("should record a successful result", () => {
      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const result: ChildRunResult = {
        runId: spec.runId,
        status: "completed",
        output: { result: "success" },
        usage: {
          durationMs: 1000,
          costUsd: 0.5,
          tokensUsed: 100,
        },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const retrieved = manager.getResult(spec.runId);
      expect(retrieved).toEqual(result);
    });

    it("should update budget when recording result", () => {
      const spec = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { budgetUsd: 5 },
      ) as any;

      const result: ChildRunResult = {
        runId: spec.runId,
        status: "completed",
        output: { result: "success" },
        usage: {
          durationMs: 1000,
          costUsd: 2,
        },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const updatedSpec = manager.getSpec(spec.runId);
      expect(updatedSpec!.budget!.consumedUsd).toBe(2);
      expect(updatedSpec!.budget!.remainingUsd).toBe(3);
    });

    it("should update fan-out state on completion", () => {
      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const result: ChildRunResult = {
        runId: spec.runId,
        status: "completed",
        output: { result: "success" },
        usage: { durationMs: 1000 },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const fanOut = manager.getFanOutState("run-parent");
      expect(fanOut!.completed).toBe(1);
      expect(fanOut!.failed).toBe(0);
      expect(fanOut!.active).toBe(0);
    });

    it("should update fan-out state on failure", () => {
      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const result: ChildRunResult = {
        runId: spec.runId,
        status: "failed",
        error: {
          code: "execution_error",
          message: "Failed",
          retryable: true,
        },
        usage: { durationMs: 500 },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const fanOut = manager.getFanOutState("run-parent");
      expect(fanOut!.completed).toBe(0);
      expect(fanOut!.failed).toBe(1);
      expect(fanOut!.active).toBe(0);
    });

    it("should throw error for unknown run ID", () => {
      const result: ChildRunResult = {
        runId: "unknown",
        status: "completed",
        output: {},
        usage: { durationMs: 1000 },
        trace: rootTrace,
        completedAt: new Date().toISOString(),
      };

      expect(() => manager.recordResult("unknown", result)).toThrow("Child run unknown not found");
    });
  });

  describe("Can Proceed Checks", () => {
    it("should allow proceeding when all limits satisfied", () => {
      const spec = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { budgetUsd: 5, deadlineMs: 60000 },
      ) as any;

      const check = manager.canProceed(spec.runId);
      expect(check.ok).toBe(true);
      expect(check.reason).toBeUndefined();
    });

    it("should reject when deadline exceeded", async () => {
      const spec = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { deadlineMs: 50 },
      ) as any;

      // Wait for deadline to pass
      await new Promise((resolve) => setTimeout(resolve, 100));

      const check = manager.canProceed(spec.runId);
      expect(check.ok).toBe(false);
      expect(check.reason).toBe("Deadline exceeded");
    });

    it("should reject when budget exhausted", () => {
      const spec = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { budgetUsd: 1 },
      ) as any;

      // Exhaust budget
      const result: ChildRunResult = {
        runId: spec.runId,
        status: "completed",
        output: {},
        usage: {
          durationMs: 1000,
          costUsd: 1.5,
        },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const check = manager.canProceed(spec.runId);
      expect(check.ok).toBe(false);
      expect(check.reason).toBe("Budget exhausted");
    });

    it("should return error for unknown run", () => {
      const check = manager.canProceed("unknown");
      expect(check.ok).toBe(false);
      expect(check.reason).toBe("Run not found");
    });
  });

  describe("Query Operations", () => {
    it("should get child runs for a parent", () => {
      manager.createChildRun("run-parent", rootTrace, limits, { task: "test1" });
      manager.createChildRun("run-parent", rootTrace, limits, { task: "test2" });
      manager.createChildRun("run-other", rootTrace, limits, { task: "test3" });

      const children = manager.getChildRuns("run-parent");
      expect(children).toHaveLength(2);
      expect(children.every((c) => c.trace.parentRunId === "run-parent")).toBe(true);
    });

    it("should get child results for a parent", () => {
      const spec1 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test1",
      }) as any;
      const spec2 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test2",
      }) as any;

      const result1: ChildRunResult = {
        runId: spec1.runId,
        status: "completed",
        output: {},
        usage: { durationMs: 1000 },
        trace: spec1.trace,
        completedAt: new Date().toISOString(),
      };

      const result2: ChildRunResult = {
        runId: spec2.runId,
        status: "completed",
        output: {},
        usage: { durationMs: 2000 },
        trace: spec2.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec1.runId, result1);
      manager.recordResult(spec2.runId, result2);

      const results = manager.getChildResults("run-parent");
      expect(results).toHaveLength(2);
      expect(results.map((r) => r.runId).sort()).toEqual([spec1.runId, spec2.runId].sort());
    });

    it("should get depth of a run", () => {
      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const depth = manager.getDepth(spec.runId);
      expect(depth).toBe(1);
    });

    it("should get trace path from root to run", () => {
      const spec1 = manager.createChildRun("run-root", rootTrace, limits, { task: "test1" }) as any;

      const spec2 = manager.createChildRun(spec1.runId, spec1.trace, limits, {
        task: "test2",
      }) as any;

      const path = manager.getTracePath(spec2.runId);
      expect(path).toEqual([spec1.runId, spec2.runId]);
    });
  });

  describe("Fan-Out State", () => {
    it("should track fan-out state correctly", () => {
      const _spec1 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test1",
      }) as any;
      const _spec2 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test2",
      }) as any;

      const fanOut = manager.getFanOutState("run-parent");
      expect(fanOut!.childRunIds).toHaveLength(2);
      expect(fanOut!.maxFanOut).toBe(5);
      expect(fanOut!.active).toBe(2);
      expect(fanOut!.completed).toBe(0);
      expect(fanOut!.failed).toBe(0);
    });

    it("should update fan-out counts on completion", () => {
      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const result: ChildRunResult = {
        runId: spec.runId,
        status: "completed",
        output: {},
        usage: { durationMs: 1000 },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const fanOut = manager.getFanOutState("run-parent");
      expect(fanOut!.active).toBe(0);
      expect(fanOut!.completed).toBe(1);
    });
  });

  describe("Statistics", () => {
    it("should aggregate statistics across all runs", () => {
      const spec1 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test1",
      }) as any;
      const spec2 = manager.createChildRun(spec1.runId, spec1.trace, limits, {
        task: "test2",
      }) as any;

      const result1: ChildRunResult = {
        runId: spec1.runId,
        status: "completed",
        output: {},
        usage: { durationMs: 1000, costUsd: 1.5 },
        trace: spec1.trace,
        completedAt: new Date().toISOString(),
      };

      const result2: ChildRunResult = {
        runId: spec2.runId,
        status: "failed",
        error: { code: "error", message: "Failed", retryable: true },
        usage: { durationMs: 500, costUsd: 0.5 },
        trace: spec2.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec1.runId, result1);
      manager.recordResult(spec2.runId, result2);

      const stats = manager.getStatistics();
      expect(stats.totalRuns).toBe(2);
      expect(stats.totalCostUsd).toBe(2);
      expect(stats.totalDurationMs).toBe(1500);
      expect(stats.byStatus.completed).toBe(1);
      expect(stats.byStatus.failed).toBe(1);
      expect(stats.byDepth.get(1)).toBe(1);
      expect(stats.byDepth.get(2)).toBe(1);
    });
  });

  describe("Cleanup", () => {
    it("should clean up a run and its descendants", () => {
      const spec1 = manager.createChildRun("run-root", rootTrace, limits, { task: "test1" }) as any;
      const spec2 = manager.createChildRun(spec1.runId, spec1.trace, limits, {
        task: "test2",
      }) as any;

      manager.cleanup(spec1.runId);

      expect(manager.getSpec(spec1.runId)).toBeUndefined();
      expect(manager.getSpec(spec2.runId)).toBeUndefined();
      expect(manager.getDepth(spec1.runId)).toBeUndefined();
    });
  });

  describe("Trace Context", () => {
    it("should maintain trace lineage", () => {
      const spec1 = manager.createChildRun("run-root", rootTrace, limits, { task: "test1" }) as any;
      const spec2 = manager.createChildRun(spec1.runId, spec1.trace, limits, {
        task: "test2",
      }) as any;

      expect(spec1.trace.traceId).toBe("trace-1");
      expect(spec1.trace.rootRunId).toBe("run-root");
      expect(spec1.trace.parentRunId).toBe("run-root");
      expect(spec1.trace.parentSpanId).toBe("span-root");

      expect(spec2.trace.traceId).toBe("trace-1");
      expect(spec2.trace.rootRunId).toBe("run-root");
      expect(spec2.trace.parentRunId).toBe(spec1.runId);
      expect(spec2.trace.parentSpanId).toBe(spec1.trace.spanId);
    });

    it("should propagate correlation and causation IDs", () => {
      const traceWithIds: TraceContext = {
        ...rootTrace,
        correlationId: "corr-123",
        causationId: "cause-456",
      };

      const spec = manager.createChildRun("run-parent", traceWithIds, limits, {
        task: "test",
      }) as any;

      expect(spec.trace.correlationId).toBe("corr-123");
      expect(spec.trace.causationId).toBe(spec.runId);
    });
  });
});
