import { beforeEach, describe, expect, it } from "vitest";
import type { PlanningRequest } from "../../src/workflow/planner.js";
import { BasicPlanner } from "../../src/workflow/planner.js";
import type { WorkflowManifest } from "../../src/workflow/workflow-module.js";
import { testScope } from "../helpers/scope.js";

describe("BasicPlanner", () => {
  let planner: BasicPlanner;

  const sampleScope = testScope();

  const sampleManifest: WorkflowManifest = {
    apiVersion: "workflow.v1",
    id: "test-workflow",
    version: "1.0.0",
    displayName: "Test Workflow",
    description: "A test workflow",
    stateSchema: {},
    outputSchema: {},
    capabilities: ["agent:researcher", "agent:analyzer", "agent:summarizer"],
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
    planner = new BasicPlanner();
  });

  describe("proposePlan", () => {
    it("should propose a sequential plan", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
        constraints: {
          preferredStrategy: "sequential",
        },
      };

      const result = await planner.proposePlan(request);

      expect(result.success).toBe(true);
      expect(result.proposal).toBeDefined();
      expect(result.proposal?.plan.nodes).toHaveLength(3);
      expect(result.proposal?.plan.edges).toHaveLength(2);
      expect(result.proposal?.workflowId).toBe("workflow-1");
      expect(result.proposal?.runId).toBe("run-1");
      expect(result.proposal?.scope).toEqual(sampleScope);
    });

    it("should propose a parallel plan", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
        constraints: {
          preferredStrategy: "parallel",
        },
      };

      const result = await planner.proposePlan(request);

      expect(result.success).toBe(true);
      expect(result.proposal).toBeDefined();
      expect(result.proposal?.plan.nodes).toHaveLength(3);
      expect(result.proposal?.plan.edges).toHaveLength(0);
    });

    it("should respect maxNodes constraint", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
        constraints: {
          maxNodes: 2,
        },
      };

      const result = await planner.proposePlan(request);

      expect(result.success).toBe(true);
      expect(result.proposal?.plan.nodes).toHaveLength(2);
    });

    it("should estimate cost and duration", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.estimatedCost).toBeGreaterThan(0);
      expect(result.proposal?.estimatedDuration).toBeGreaterThan(0);
    });

    it("should assess risk level", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.riskLevel).toMatch(/low|medium|high/);
    });

    it("should determine approval requirement", async () => {
      const lowCostManifest = {
        ...sampleManifest,
        capabilities: ["agent:test"],
      };

      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: lowCostManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.requiresApproval).toBeDefined();
    });

    it("should require approval for manifest with requiresApproval flag", async () => {
      const approvalManifest = {
        ...sampleManifest,
        limits: {
          ...sampleManifest.limits,
          requiresApproval: true,
        },
      };

      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: approvalManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.requiresApproval).toBe(true);
    });

    it("should generate rationale", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.rationale).toBeDefined();
      expect(result.proposal?.rationale).toContain("workflow-1");
    });

    it("should set checkpoint boundaries", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);

      const hasCheckpoint = result.proposal?.plan.nodes.some((n) => n.checkpointBoundary);
      expect(hasCheckpoint).toBe(true);
    });

    it("should store proposal for retrieval", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);
      const proposalId = result.proposal!.proposalId;

      const retrieved = planner.getProposal(proposalId);
      expect(retrieved).toBeDefined();
      expect(retrieved?.proposalId).toBe(proposalId);
    });
  });

  describe("revisePlan", () => {
    it("should revise an existing plan", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const original = await planner.proposePlan(request);
      const proposalId = original.proposal!.proposalId;

      const revised = await planner.revisePlan(proposalId, "Make it faster", { maxNodes: 2 });

      expect(revised.success).toBe(true);
      expect(revised.proposal).toBeDefined();
      expect(revised.proposal?.plan.nodes.length).toBeLessThanOrEqual(2);
      // Revision keeps the host-bound scope of the original request
      expect(revised.proposal?.scope).toEqual(sampleScope);
    });

    it("should fail for non-existent proposal", async () => {
      const result = await planner.revisePlan("non-existent", "Make it faster");

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
      expect(result.error?.code).toBe("proposal_not_found");
    });
  });

  describe("getProposal", () => {
    it("should return undefined for non-existent proposal", () => {
      const proposal = planner.getProposal("non-existent");
      expect(proposal).toBeUndefined();
    });

    it("should return proposal by ID", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
      };

      const result = await planner.proposePlan(request);
      const proposalId = result.proposal!.proposalId;

      const retrieved = planner.getProposal(proposalId);
      expect(retrieved).toBeDefined();
      expect(retrieved?.workflowId).toBe("workflow-1");
      expect(retrieved?.runId).toBe("run-1");
    });
  });

  describe("budget calculation", () => {
    it("should respect cost constraint", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
        constraints: {
          maxCost: 0.02,
        },
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.plan.budget.maxCostUsd).toBeLessThanOrEqual(0.02);
    });

    it("should respect duration constraint", async () => {
      const request: PlanningRequest = {
        workflowId: "workflow-1",
        runId: "run-1",
        manifest: sampleManifest,
        scope: sampleScope,
        input: { query: "test" },
        context: {} as any,
        constraints: {
          maxDuration: 10000,
        },
      };

      const result = await planner.proposePlan(request);

      expect(result.proposal?.plan.budget.maxDurationMs).toBeLessThanOrEqual(10000);
    });
  });
});
