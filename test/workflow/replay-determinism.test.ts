import { beforeEach, describe, expect, it } from "vitest";
import { NodeLifecycleManager } from "../../src/workflow/node-lifecycle.js";
import { BasicPlanner } from "../../src/workflow/planner.js";
import type { WorkflowManifest } from "../../src/workflow/workflow-module.js";
import { WorkflowPersistence } from "../../src/workflow/workflow-persistence.js";
import { testScope } from "../helpers/scope.js";

describe("Workflow Replay and Determinism", () => {
  let persistence: WorkflowPersistence;
  let planner: BasicPlanner;
  let lifecycle: NodeLifecycleManager;

  const sampleScope = testScope();

  const sampleManifest: WorkflowManifest = {
    apiVersion: "workflow.v1",
    id: "test-workflow",
    version: "1.0.0",
    displayName: "Test Workflow",
    description: "A test workflow",
    stateSchema: {},
    outputSchema: {},
    capabilities: ["agent:researcher", "agent:analyzer"],
    requiredPorts: ["planner", "executor"],
    limits: {
      maxNodes: 10,
      maxDepth: 5,
      maxFanOut: 3,
      maxDurationMs: 60000,
      maxCostUsd: 1.0,
      requiresApproval: false,
    },
  };

  beforeEach(() => {
    persistence = new WorkflowPersistence();
    planner = new BasicPlanner();
    lifecycle = new NodeLifecycleManager();
  });

  describe("manifest pinning and retrieval", () => {
    it("should pin manifest on execution creation", async () => {
      const execution = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
      );

      const pin = persistence.getPinnedManifest(execution.manifestHash);
      expect(pin).toBeDefined();
      expect(pin?.manifest).toEqual(sampleManifest);
    });

    it("should pin plan on update", async () => {
      const execution = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
      );

      const planResult = await planner.proposePlan({
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: {},
        context: {} as any,
      });

      await persistence.updatePlan("run-1", planResult.proposal!.plan);

      const planPin = persistence.getPinnedManifest(execution.planHash!);
      expect(planPin).toBeDefined();
      expect(planPin?.manifest).toEqual(planResult.proposal!.plan);
    });

    it("should increment usage count on reuse", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const execution1 = persistence.getExecution("run-1");
      const hash1 = execution1!.manifestHash;

      await persistence.createExecution("workflow-2", "run-2", sampleManifest, sampleScope);

      const pin = persistence.getPinnedManifest(hash1);
      expect(pin?.usageCount).toBe(2);
    });

    it("should use same hash for identical manifests", async () => {
      const exec1 = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
      );

      const exec2 = await persistence.createExecution(
        "workflow-2",
        "run-2",
        sampleManifest,
        sampleScope,
      );

      expect(exec1.manifestHash).toBe(exec2.manifestHash);
    });

    it("should use different hash for different manifests", async () => {
      const exec1 = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
      );

      const differentManifest = {
        ...sampleManifest,
        version: "2.0.0",
      };

      const exec2 = await persistence.createExecution(
        "workflow-2",
        "run-2",
        differentManifest,
        sampleScope,
      );

      expect(exec1.manifestHash).not.toBe(exec2.manifestHash);
    });
  });

  describe("checkpoint replay", () => {
    it("should include manifest and plan hashes in checkpoint", async () => {
      const execution = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
      );

      const planResult = await planner.proposePlan({
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: {},
        context: {} as any,
      });

      await persistence.updatePlan("run-1", planResult.proposal!.plan);

      const checkpoint = await persistence.persistCheckpoint("run-1", { progress: 50 }, "node-1");

      expect(checkpoint.manifestHash).toBe(execution.manifestHash);
      expect(checkpoint.planHash).toBe(execution.planHash);
    });

    it("should be able to retrieve manifest from checkpoint", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const checkpoint = await persistence.persistCheckpoint("run-1", { progress: 50 });

      const manifestPin = persistence.getPinnedManifest(checkpoint.manifestHash);
      expect(manifestPin?.manifest).toEqual(sampleManifest);
    });

    it("should be able to retrieve plan from checkpoint", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const planResult = await planner.proposePlan({
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: {},
        context: {} as any,
      });

      await persistence.updatePlan("run-1", planResult.proposal!.plan);

      const checkpoint = await persistence.persistCheckpoint("run-1", { progress: 50 });

      const planPin = persistence.getPinnedManifest(checkpoint.planHash!);
      expect(planPin?.manifest).toEqual(planResult.proposal!.plan);
    });

    it("should hash checkpoint state for comparison", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const state1 = { progress: 50, data: "test" };
      const checkpoint1 = await persistence.persistCheckpoint("run-1", state1);

      const state2 = { progress: 50, data: "test" };
      const checkpoint2 = await persistence.persistCheckpoint("run-1", state2);

      expect(checkpoint1.stateHash).toBe(checkpoint2.stateHash);
    });

    it("should detect different checkpoint states", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const checkpoint1 = await persistence.persistCheckpoint("run-1", { progress: 50 });

      const checkpoint2 = await persistence.persistCheckpoint("run-1", { progress: 75 });

      expect(checkpoint1.stateHash).not.toBe(checkpoint2.stateHash);
    });
  });

  describe("execution determinism", () => {
    it("should produce same plan for identical inputs", async () => {
      const request1 = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
        constraints: { preferredStrategy: "sequential" as const },
      };

      const result1 = await planner.proposePlan(request1);

      const request2 = {
        ...request1,
        runId: "run-2",
      };

      const result2 = await planner.proposePlan(request2);

      expect(result1.proposal?.plan.nodes.length).toBe(result2.proposal?.plan.nodes.length);
      expect(result1.proposal?.plan.edges.length).toBe(result2.proposal?.plan.edges.length);
    });

    it("should track execution order through events", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step1 = await persistence.createStep("run-1", "node-1", "attempt-1");
      await persistence.updateStepStatus(step1.stepId, "completed");

      const step2 = await persistence.createStep("run-1", "node-2", "attempt-2");
      await persistence.updateStepStatus(step2.stepId, "completed");

      const events = persistence.getEvents("run-1");
      const stepEvents = events.filter((e) => e.type.startsWith("step."));

      expect(stepEvents).toHaveLength(4);
      expect(stepEvents[0].type).toBe("step.created");
      expect(stepEvents[0].nodeId).toBe("node-1");
      expect(stepEvents[1].type).toBe("step.completed");
      expect(stepEvents[2].nodeId).toBe("node-2");
    });

    it("should maintain execution state across checkpoints", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step = await persistence.createStep("run-1", "node-1", "attempt-1");
      await persistence.updateStepStatus(step.stepId, "running");

      const checkpoint1 = await persistence.persistCheckpoint("run-1", { progress: 25 }, "node-1");

      await persistence.updateStepStatus(step.stepId, "completed", {}, undefined, 1000);

      const checkpoint2 = await persistence.persistCheckpoint("run-1", { progress: 100 }, "node-1");

      const checkpoints = persistence.getCheckpoints("run-1");
      expect(checkpoints).toHaveLength(2);
      expect(checkpoints[0].id).toBe(checkpoint1.id);
      expect(checkpoints[1].id).toBe(checkpoint2.id);
    });
  });

  describe("node lifecycle determinism", () => {
    it("should track all attempts for a node", async () => {
      await lifecycle.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: { test: "data" },
      });

      await lifecycle.fail({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        error: { code: "transient_error", message: "Retry", retryable: true },
        usage: { durationMs: 500 },
      });

      await lifecycle.resume({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-2",
      });

      await lifecycle.complete({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-2",
        output: { result: "success" },
        usage: { durationMs: 800 },
      });

      const execution = lifecycle.getExecution("run-1", "node-1");
      expect(execution?.attempts).toHaveLength(2);
      expect(execution?.attempts[0].attemptId).toBe("attempt-1");
      expect(execution?.attempts[0].status).toBe("failed");
      expect(execution?.attempts[1].attemptId).toBe("attempt-2");
      expect(execution?.attempts[1].status).toBe("completed");
    });

    it("should preserve checkpoint history", async () => {
      await lifecycle.start({
        nodeId: "node-1",
        runId: "run-1",
        attemptId: "attempt-1",
        input: { test: "data" },
      });

      await lifecycle.checkpoint({
        nodeId: "node-1",
        runId: "run-1",
        state: { progress: 33 },
      });

      await lifecycle.checkpoint({
        nodeId: "node-1",
        runId: "run-1",
        state: { progress: 66 },
      });

      await lifecycle.checkpoint({
        nodeId: "node-1",
        runId: "run-1",
        state: { progress: 100 },
      });

      const execution = lifecycle.getExecution("run-1", "node-1");
      expect(execution?.checkpoints).toHaveLength(3);
      expect(execution?.checkpoints[0].state).toEqual({ progress: 33 });
      expect(execution?.checkpoints[2].state).toEqual({ progress: 100 });
    });
  });

  describe("usage accumulation", () => {
    it("should accumulate usage across steps", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step1 = await persistence.createStep("run-1", "node-1", "attempt-1");
      await persistence.updateStepStatus(step1.stepId, "completed", {}, undefined, 1000, 0.001);

      const step2 = await persistence.createStep("run-1", "node-2", "attempt-2");
      await persistence.updateStepStatus(step2.stepId, "completed", {}, undefined, 2000, 0.003);

      const step3 = await persistence.createStep("run-1", "node-3", "attempt-3");
      await persistence.updateStepStatus(step3.stepId, "completed", {}, undefined, 1500, 0.002);

      const execution = persistence.getExecution("run-1");
      expect(execution?.usage.durationMs).toBe(4500);
      expect(execution?.usage.costUsd).toBe(0.006);
      expect(execution?.usage.nodesExecuted).toBe(3);
    });

    it("should track usage in records", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step1 = await persistence.createStep("run-1", "node-1", "attempt-1");
      await persistence.updateStepStatus(step1.stepId, "completed", {}, undefined, 1000, 0.001);

      const step2 = await persistence.createStep("run-1", "node-2", "attempt-2");
      await persistence.updateStepStatus(step2.stepId, "completed", {}, undefined, 2000, 0.003);

      const records = persistence.getUsageRecords("run-1");
      expect(records).toHaveLength(2);
      expect(records[0].durationMs).toBe(1000);
      expect(records[0].costUsd).toBe(0.001);
      expect(records[1].durationMs).toBe(2000);
      expect(records[1].costUsd).toBe(0.003);
    });
  });

  describe("parent-child hierarchy", () => {
    it("should track workflow hierarchy", async () => {
      const _parent = await persistence.createExecution(
        "parent-workflow",
        "parent-run",
        sampleManifest,
        sampleScope,
      );

      const _child1 = await persistence.createExecution(
        "child-workflow-1",
        "child-run-1",
        sampleManifest,
        sampleScope,
        {},
        "parent-run",
      );

      const _child2 = await persistence.createExecution(
        "child-workflow-2",
        "child-run-2",
        sampleManifest,
        sampleScope,
        {},
        "parent-run",
      );

      const children = persistence.getChildren("parent-run");
      expect(children).toHaveLength(2);
      expect(children.map((c) => c.childRunId)).toContain("child-run-1");
      expect(children.map((c) => c.childRunId)).toContain("child-run-2");
    });

    it("should preserve relationship type", async () => {
      await persistence.createExecution(
        "parent-workflow",
        "parent-run",
        sampleManifest,
        sampleScope,
      );

      await persistence.createExecution(
        "child-workflow",
        "child-run",
        sampleManifest,
        sampleScope,
        {},
        "parent-run",
      );

      const children = persistence.getChildren("parent-run");
      expect(children[0].relationshipType).toBe("subworkflow");
    });
  });
});
