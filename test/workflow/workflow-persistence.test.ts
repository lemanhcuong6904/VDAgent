import { beforeEach, describe, expect, it } from "vitest";
import type {
  PlanSpec,
  WorkflowError,
  WorkflowManifest,
} from "../../src/workflow/workflow-module.js";
import { WorkflowPersistence } from "../../src/workflow/workflow-persistence.js";
import { testScope } from "../helpers/scope.js";

describe("WorkflowPersistence", () => {
  let persistence: WorkflowPersistence;

  const sampleScope = testScope();

  const sampleManifest: WorkflowManifest = {
    apiVersion: "workflow.v1",
    id: "test-workflow",
    version: "1.0.0",
    displayName: "Test Workflow",
    description: "A test workflow",
    stateSchema: {},
    outputSchema: {},
    capabilities: ["agent:test-agent"],
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

  const samplePlan: PlanSpec = {
    version: "plan.v1",
    workflowId: "test-workflow",
    nodes: [
      {
        id: "node-1",
        type: "agent",
        displayName: "Test Node",
        agentId: "test-agent",
        inputSchema: {},
        outputSchema: {},
        timeout: 30000,
        retryPolicy: {
          class: "transient",
          maxAttempts: 3,
          backoffMs: 1000,
        },
        checkpointBoundary: false,
      },
    ],
    edges: [],
    budget: {
      maxCostUsd: 1.0,
      maxDurationMs: 60000,
      maxModelTokens: 100000,
      maxToolCalls: 10,
    },
  };

  beforeEach(() => {
    persistence = new WorkflowPersistence();
  });

  describe("createExecution", () => {
    it("should create a workflow execution", async () => {
      const execution = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
        { input: "test" },
      );

      expect(execution.workflowId).toBe("workflow-1");
      expect(execution.runId).toBe("run-1");
      expect(execution.status).toBe("pending");
      expect(execution.manifest).toEqual(sampleManifest);
      expect(execution.manifestHash).toBeDefined();
      expect(execution.input).toEqual({ input: "test" });
      expect(execution.usage.durationMs).toBe(0);
      expect(execution.checkpoints).toHaveLength(0);
      expect(execution.events).toHaveLength(1);
    });

    it("should record parent-child relationship", async () => {
      await persistence.createExecution(
        "parent-workflow",
        "parent-run",
        sampleManifest,
        sampleScope,
      );

      const childExecution = await persistence.createExecution(
        "child-workflow",
        "child-run",
        sampleManifest,
        sampleScope,
        undefined,
        "parent-run",
      );

      expect(childExecution.parentRunId).toBe("parent-run");

      const children = persistence.getChildren("parent-run");
      expect(children).toHaveLength(1);
      expect(children[0].childRunId).toBe("child-run");
      expect(children[0].relationshipType).toBe("subworkflow");
    });

    it("should pin manifest", async () => {
      const execution = await persistence.createExecution(
        "workflow-1",
        "run-1",
        sampleManifest,
        sampleScope,
      );

      const pin = persistence.getPinnedManifest(execution.manifestHash);
      expect(pin).toBeDefined();
      expect(pin?.manifest).toEqual(sampleManifest);
      expect(pin?.usageCount).toBe(1);
    });
  });

  describe("updatePlan", () => {
    it("should update workflow plan", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.updatePlan("run-1", samplePlan);

      const execution = persistence.getExecution("run-1");
      expect(execution?.plan).toEqual(samplePlan);
      expect(execution?.planHash).toBeDefined();

      const pin = persistence.getPinnedManifest(execution!.planHash!);
      expect(pin).toBeDefined();
      expect(pin?.manifest).toEqual(samplePlan);
    });

    it("should record plan update event", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.updatePlan("run-1", samplePlan);

      const events = persistence.getEvents("run-1");
      const planEvent = events.find((e) => e.type === "workflow.plan_updated");
      expect(planEvent).toBeDefined();
      expect(planEvent?.data.nodeCount).toBe(1);
    });
  });

  describe("updateExecutionStatus", () => {
    it("should update execution status", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.updateExecutionStatus("run-1", "running");

      const execution = persistence.getExecution("run-1");
      expect(execution?.status).toBe("running");
    });

    it("should record output on completion", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.updateExecutionStatus("run-1", "completed", { result: "success" });

      const execution = persistence.getExecution("run-1");
      expect(execution?.status).toBe("completed");
      expect(execution?.output).toEqual({ result: "success" });
      expect(execution?.completedAt).toBeDefined();
    });

    it("should record errors on failure", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const error: WorkflowError = {
        code: "execution_failed",
        message: "Test error",
        retryable: false,
      };

      await persistence.updateExecutionStatus("run-1", "failed", undefined, error);

      const execution = persistence.getExecution("run-1");
      expect(execution?.status).toBe("failed");
      expect(execution?.errors).toHaveLength(1);
      expect(execution?.errors[0]).toEqual(error);
    });
  });

  describe("createStep", () => {
    it("should create a workflow step", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step = await persistence.createStep("run-1", "node-1", "attempt-1", {
        message: "test",
      });

      expect(step.stepId).toBeDefined();
      expect(step.runId).toBe("run-1");
      expect(step.nodeId).toBe("node-1");
      expect(step.attemptId).toBe("attempt-1");
      expect(step.status).toBe("pending");
      expect(step.input).toEqual({ message: "test" });
    });

    it("should increment nodes executed count", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.createStep("run-1", "node-1", "attempt-1");
      await persistence.createStep("run-1", "node-2", "attempt-2");

      const execution = persistence.getExecution("run-1");
      expect(execution?.usage.nodesExecuted).toBe(2);
    });

    it("should support parent step relationship", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const parentStep = await persistence.createStep("run-1", "parent-node", "attempt-1");
      const childStep = await persistence.createStep(
        "run-1",
        "child-node",
        "attempt-2",
        {},
        parentStep.stepId,
      );

      expect(childStep.parentStepId).toBe(parentStep.stepId);
    });
  });

  describe("updateStepStatus", () => {
    it("should update step status", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step = await persistence.createStep("run-1", "node-1", "attempt-1");

      await persistence.updateStepStatus(step.stepId, "running");

      const updatedStep = persistence.getStep(step.stepId);
      expect(updatedStep?.status).toBe("running");
    });

    it("should complete step with output and usage", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step = await persistence.createStep("run-1", "node-1", "attempt-1");

      await persistence.updateStepStatus(
        step.stepId,
        "completed",
        { result: "success" },
        undefined,
        1500,
        0.002,
      );

      const updatedStep = persistence.getStep(step.stepId);
      expect(updatedStep?.status).toBe("completed");
      expect(updatedStep?.output).toEqual({ result: "success" });
      expect(updatedStep?.durationMs).toBe(1500);
      expect(updatedStep?.costUsd).toBe(0.002);
      expect(updatedStep?.completedAt).toBeDefined();

      const usageRecords = persistence.getUsageRecords("run-1");
      expect(usageRecords).toHaveLength(1);
      expect(usageRecords[0].durationMs).toBe(1500);
    });

    it("should accumulate usage in execution", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const step1 = await persistence.createStep("run-1", "node-1", "attempt-1");
      const step2 = await persistence.createStep("run-1", "node-2", "attempt-2");

      await persistence.updateStepStatus(step1.stepId, "completed", {}, undefined, 1000, 0.001);
      await persistence.updateStepStatus(step2.stepId, "completed", {}, undefined, 2000, 0.003);

      const execution = persistence.getExecution("run-1");
      expect(execution?.usage.durationMs).toBe(3000);
      expect(execution?.usage.costUsd).toBe(0.004);
    });
  });

  describe("persistCheckpoint", () => {
    it("should persist a checkpoint", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      const checkpoint = await persistence.persistCheckpoint("run-1", { progress: 50 }, "node-1");

      expect(checkpoint.id).toBeDefined();
      expect(checkpoint.runId).toBe("run-1");
      expect(checkpoint.nodeId).toBe("node-1");
      expect(checkpoint.state).toEqual({ progress: 50 });
      expect(checkpoint.stateHash).toBeDefined();
      expect(checkpoint.manifestHash).toBeDefined();
    });

    it("should add checkpoint to execution", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.persistCheckpoint("run-1", { progress: 50 }, "node-1");
      await persistence.persistCheckpoint("run-1", { progress: 100 }, "node-1");

      const execution = persistence.getExecution("run-1");
      expect(execution?.checkpoints).toHaveLength(2);
    });

    it("should include plan hash if plan exists", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.updatePlan("run-1", samplePlan);

      const checkpoint = await persistence.persistCheckpoint("run-1", { progress: 50 });

      expect(checkpoint.planHash).toBeDefined();
    });
  });

  describe("getSteps", () => {
    it("should get all steps for a run", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.createStep("run-1", "node-1", "attempt-1");
      await persistence.createStep("run-1", "node-2", "attempt-2");

      const steps = persistence.getSteps("run-1");
      expect(steps).toHaveLength(2);
    });
  });

  describe("getCheckpoints", () => {
    it("should get all checkpoints for a run", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.persistCheckpoint("run-1", { step: 1 });
      await persistence.persistCheckpoint("run-1", { step: 2 });

      const checkpoints = persistence.getCheckpoints("run-1");
      expect(checkpoints).toHaveLength(2);
    });
  });

  describe("getEvents", () => {
    it("should get all events for a run", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope);

      await persistence.updateExecutionStatus("run-1", "running");
      await persistence.updateExecutionStatus("run-1", "completed");

      const events = persistence.getEvents("run-1");
      expect(events.length).toBeGreaterThanOrEqual(3);
      expect(events.some((e) => e.type === "workflow.created")).toBe(true);
      expect(events.some((e) => e.type === "workflow.running")).toBe(true);
      expect(events.some((e) => e.type === "workflow.completed")).toBe(true);
    });
  });

  describe("getExecutionSummary", () => {
    it("should get execution summary", async () => {
      await persistence.createExecution("workflow-1", "run-1", sampleManifest, sampleScope, {
        input: "test",
      });

      const step1 = await persistence.createStep("run-1", "node-1", "attempt-1");
      const step2 = await persistence.createStep("run-1", "node-2", "attempt-2");

      await persistence.updateStepStatus(step1.stepId, "completed", {}, undefined, 1000);
      await persistence.updateStepStatus(step2.stepId, "completed", {}, undefined, 2000);

      await persistence.persistCheckpoint("run-1", { progress: 100 });

      await persistence.updateExecutionStatus("run-1", "completed", { result: "success" });

      const summary = persistence.getExecutionSummary("run-1");
      expect(summary).toBeDefined();
      expect(summary?.runId).toBe("run-1");
      expect(summary?.workflowId).toBe("workflow-1");
      expect(summary?.status).toBe("completed");
      expect(summary?.stepCount).toBe(2);
      expect(summary?.checkpointCount).toBe(1);
      expect(summary?.hasOutput).toBe(true);
    });
  });
});
