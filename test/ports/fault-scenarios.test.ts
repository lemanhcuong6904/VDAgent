import { beforeEach, describe, expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/index.js";
import {
  type AgentHandler,
  type DelegationRequest,
  InMemoryCollaborationPort,
} from "../../src/ports/collaboration-port.js";
import {
  type HandoffItem,
  InMemoryMailbox,
  type Message,
  type Question,
  type Result,
} from "../../src/ports/mailbox.js";
import {
  type ChildRunLimits,
  ChildRunManager,
  type TraceContext,
} from "../../src/workflow/child-run.js";
import { testScope } from "../helpers/scope.js";

describe("Fault Scenarios", () => {
  let scope: AgentScope;

  beforeEach(() => {
    scope = testScope({ actorId: "actor-1" });
  });

  describe("Crash Before Commit", () => {
    it("should allow retry after crash before recording result", async () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      // Simulate crash: child run created but no result recorded
      expect(manager.getSpec(spec.runId)).toBeDefined();
      expect(manager.getResult(spec.runId)).toBeUndefined();

      // On recovery, can proceed again
      const canProceed = manager.canProceed(spec.runId);
      expect(canProceed.ok).toBe(true);
    });

    it("should handle mailbox message sent but not processed", async () => {
      const mailbox = new InMemoryMailbox();

      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const message: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      await mailbox.ask(message);

      // Crash before agent-b processes message
      const messages = await mailbox.receive("agent-b");
      expect(messages).toHaveLength(1);

      // On recovery, message still available
      // (In production, would need persistent mailbox)
    });
  });

  describe("Crash After Commit", () => {
    it("should prevent duplicate result recording", async () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const result = {
        runId: spec.runId,
        status: "completed" as const,
        output: { result: "done" },
        usage: { durationMs: 1000, costUsd: 0.5 },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      // First commit
      manager.recordResult(spec.runId, result);

      const firstResult = manager.getResult(spec.runId);
      expect(firstResult).toBeDefined();

      // Crash after commit, replay on recovery
      // Should be idempotent (overwrite with same data)
      manager.recordResult(spec.runId, result);

      const secondResult = manager.getResult(spec.runId);
      expect(secondResult).toEqual(firstResult);
    });

    it("should reject duplicate mailbox answer", async () => {
      const mailbox = new InMemoryMailbox();

      const result: Result = {
        type: "result",
        questionId: "q-1",
        status: "success",
        output: { result: "done" },
      };

      const message: Message<Result> = {
        messageId: "msg-1",
        fromAgentId: "agent-b",
        toAgentId: "agent-a",
        scope,
        content: result,
        timestamp: new Date().toISOString(),
      };

      // First answer
      const first = await mailbox.answer(message);
      expect(first.delivered).toBe(true);

      // Crash after commit, replay on recovery
      const second = await mailbox.answer(message);
      expect(second.delivered).toBe(false); // Bounced as duplicate
    });
  });

  describe("State Loss (Redis/Storage Failure)", () => {
    it("should handle complete state loss in child run manager", () => {
      const manager1 = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec = manager1.createChildRun("run-parent", rootTrace, limits, {
        task: "test",
      }) as any;

      // Simulate complete state loss
      const manager2 = new ChildRunManager();

      // State is gone
      expect(manager2.getSpec(spec.runId)).toBeUndefined();

      // In production, would need to rebuild from event log or durable store
    });

    it("should handle mailbox state loss", async () => {
      const mailbox1 = new InMemoryMailbox();

      const question: Question = {
        type: "question",
        questionId: "q-1",
        input: { task: "test" },
      };

      const message: Message<Question> = {
        messageId: "msg-1",
        fromAgentId: "agent-a",
        toAgentId: "agent-b",
        scope,
        content: question,
        timestamp: new Date().toISOString(),
      };

      await mailbox1.ask(message);

      // Simulate state loss
      const mailbox2 = new InMemoryMailbox();

      // Messages lost
      const messages = await mailbox2.receive("agent-b");
      expect(messages).toHaveLength(0);

      // Dedup state also lost - duplicate would be accepted
      const isDup = await mailbox2.isDuplicate("msg-1");
      expect(isDup).toBe(false);

      // In production, need persistent storage
    });
  });

  describe("Duplicate Execution", () => {
    it("should handle duplicate async invocation", async () => {
      const port = new InMemoryCollaborationPort();

      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          return { result: "done", timestamp: Date.now() };
        },
      };

      port.registerAgent(
        {
          agentId: "worker",
          name: "Worker",
          description: "Test worker",
          capabilities: ["work"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "worker",
        scope,
        input: { task: "test" },
      };

      const handle1 = await port.invokeAsync(request);
      const result1 = await handle1.wait(5000);

      expect(result1.status).toBe("completed");

      // Attempt duplicate with same requestId (idempotency check)
      // In a real system, should detect duplicate and return cached result
      // For now, in-memory port would create new execution
      // This test documents the behavior
    });

    it("should prevent double claim of work item (CAS)", async () => {
      const mailbox = new InMemoryMailbox();

      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);

      // Worker 1 claims with version 0
      const claim1 = await mailbox.claimWork("item-1", "worker-1", 0);
      expect(claim1.success).toBe(true);
      expect(claim1.item?.version).toBe(1);

      // Worker 2 tries to claim with stale version 0 (should fail)
      const claim2 = await mailbox.claimWork("item-1", "worker-2", 0);
      expect(claim2.success).toBe(false);

      // Worker 2 tries with updated version (should also fail - already claimed)
      const claim3 = await mailbox.claimWork("item-1", "worker-2", 1);
      expect(claim3.success).toBe(false);
    });
  });

  describe("Stale Lease", () => {
    it("should detect stale work claim via version mismatch", async () => {
      const mailbox = new InMemoryMailbox();

      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);

      // Worker claims
      const claim = await mailbox.claimWork("item-1", "worker-1", 0);
      expect(claim.success).toBe(true);

      // Simulate lease expiry: coordinator releases it
      await mailbox.releaseWork("item-1", "worker-1");

      // Worker tries to complete with stale claim
      const complete = await mailbox.completeWork("item-1", "worker-1");
      expect(complete.success).toBe(false); // Fails - no longer owner

      // Another worker can claim it
      const claim2 = await mailbox.claimWork("item-1", "worker-2", 2);
      expect(claim2.success).toBe(true);
    });

    it("should reject completion by wrong owner", async () => {
      const mailbox = new InMemoryMailbox();

      const item: HandoffItem = {
        itemId: "item-1",
        workType: "analysis",
        payload: { data: "test" },
        version: 0,
        ownerId: null,
        status: "available",
        createdAt: new Date().toISOString(),
      };

      await mailbox.addWorkItem(item);
      await mailbox.claimWork("item-1", "worker-1", 0);

      // Worker 2 tries to complete worker 1's work
      const complete = await mailbox.completeWork("item-1", "worker-2");
      expect(complete.success).toBe(false);
    });
  });

  describe("Child Failure Propagation", () => {
    it("should record child failure in fan-out state", async () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec = manager.createChildRun("run-parent", rootTrace, limits, { task: "test" }) as any;

      const failureResult = {
        runId: spec.runId,
        status: "failed" as const,
        error: {
          code: "execution_error",
          message: "Child crashed",
          retryable: true,
        },
        usage: { durationMs: 500 },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, failureResult);

      const fanOut = manager.getFanOutState("run-parent");
      expect(fanOut?.failed).toBe(1);
      expect(fanOut?.completed).toBe(0);
      expect(fanOut?.active).toBe(0);
    });

    it("should track budget exhaustion failure", async () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { budgetUsd: 1 },
      ) as any;

      // Consume more than budget
      const result = {
        runId: spec.runId,
        status: "budget_exceeded" as const,
        usage: {
          durationMs: 1000,
          costUsd: 1.5,
        },
        trace: spec.trace,
        completedAt: new Date().toISOString(),
      };

      manager.recordResult(spec.runId, result);

      const updatedSpec = manager.getSpec(spec.runId);
      expect(updatedSpec?.budget?.remainingUsd).toBe(0);

      const canProceed = manager.canProceed(spec.runId);
      expect(canProceed.ok).toBe(false);
      expect(canProceed.reason).toBe("Budget exhausted");
    });

    it("should detect deadline exceeded", async () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec = manager.createChildRun(
        "run-parent",
        rootTrace,
        limits,
        { task: "test" },
        { deadlineMs: 50 },
      ) as any;

      // Wait for deadline to pass
      await new Promise((resolve) => setTimeout(resolve, 100));

      const canProceed = manager.canProceed(spec.runId);
      expect(canProceed.ok).toBe(false);
      expect(canProceed.reason).toBe("Deadline exceeded");
    });

    it("should handle delegation failure", async () => {
      const port = new InMemoryCollaborationPort();

      const handler: AgentHandler = {
        execute: async (_input: unknown) => {
          throw new Error("Worker crashed");
        },
      };

      port.registerAgent(
        {
          agentId: "failing-worker",
          name: "Failing Worker",
          description: "Always fails",
          capabilities: ["fail"],
        },
        handler,
      );

      const request: DelegationRequest = {
        requestId: "req-1",
        callerRunId: "run-1",
        targetAgentId: "failing-worker",
        scope,
        input: {},
      };

      const result = await port.invoke(request);

      expect(result.status).toBe("failed");
      expect(result.error?.code).toBe("execution_error");
      expect(result.error?.retryable).toBe(true);
    });
  });

  describe("Recovery Scenarios", () => {
    it("should allow statistics gathering after partial failures", () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      // Create 3 children
      const spec1 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test1",
      }) as any;
      const spec2 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test2",
      }) as any;
      const spec3 = manager.createChildRun("run-parent", rootTrace, limits, {
        task: "test3",
      }) as any;

      // 1 succeeds
      manager.recordResult(spec1.runId, {
        runId: spec1.runId,
        status: "completed",
        output: {},
        usage: { durationMs: 1000, costUsd: 1 },
        trace: spec1.trace,
        completedAt: new Date().toISOString(),
      });

      // 1 fails
      manager.recordResult(spec2.runId, {
        runId: spec2.runId,
        status: "failed",
        error: { code: "error", message: "Failed", retryable: true },
        usage: { durationMs: 500, costUsd: 0.5 },
        trace: spec2.trace,
        completedAt: new Date().toISOString(),
      });

      // 1 times out
      manager.recordResult(spec3.runId, {
        runId: spec3.runId,
        status: "timeout",
        error: { code: "timeout", message: "Timeout", retryable: true },
        usage: { durationMs: 5000, costUsd: 2 },
        trace: spec3.trace,
        completedAt: new Date().toISOString(),
      });

      const stats = manager.getStatistics();

      expect(stats.totalRuns).toBe(3);
      expect(stats.totalCostUsd).toBe(3.5);
      expect(stats.totalDurationMs).toBe(6500);
      expect(stats.byStatus.completed).toBe(1);
      expect(stats.byStatus.failed).toBe(1);
      expect(stats.byStatus.timeout).toBe(1);
    });

    it("should support cleanup after failure", () => {
      const manager = new ChildRunManager();

      const rootTrace: TraceContext = {
        traceId: "trace-1",
        spanId: "span-root",
        depth: 0,
        rootRunId: "run-root",
        parentRunId: "run-root",
      };

      const limits: ChildRunLimits = {
        maxDepth: 3,
        maxFanOut: 5,
      };

      const spec1 = manager.createChildRun("run-root", rootTrace, limits, { task: "test1" }) as any;
      const spec2 = manager.createChildRun(spec1.runId, spec1.trace, limits, {
        task: "test2",
      }) as any;

      manager.recordResult(spec2.runId, {
        runId: spec2.runId,
        status: "failed",
        error: { code: "error", message: "Failed", retryable: false },
        usage: { durationMs: 100 },
        trace: spec2.trace,
        completedAt: new Date().toISOString(),
      });

      // Clean up failed subtree
      manager.cleanup(spec1.runId);

      expect(manager.getSpec(spec1.runId)).toBeUndefined();
      expect(manager.getSpec(spec2.runId)).toBeUndefined();
    });
  });
});
