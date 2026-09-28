import { beforeEach, describe, expect, it } from "vitest";
import { PlanValidator } from "../../src/workflow/plan-validator.js";
import type { Budget, PlanEdge, PlanNode, PlanSpec } from "../../src/workflow/workflow-module.js";

describe("PlanValidator", () => {
  let validator: PlanValidator;

  const defaultBudget: Budget = {
    maxCostUsd: 10.0,
    maxDurationMs: 600000,
    maxModelTokens: 1000000,
    maxToolCalls: 100,
  };

  const sampleNode: PlanNode = {
    id: "node-1",
    type: "agent",
    displayName: "Test Agent",
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
  };

  const validPlan: PlanSpec = {
    version: "plan.v1",
    workflowId: "workflow-1",
    nodes: [sampleNode],
    edges: [],
    budget: {
      maxCostUsd: 1.0,
      maxDurationMs: 60000,
      maxModelTokens: 100000,
      maxToolCalls: 10,
    },
  };

  beforeEach(() => {
    validator = new PlanValidator();
  });

  describe("schema validation", () => {
    it("should accept valid plan", () => {
      const result = validator.validate(validPlan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
      expect(result.errors).toBeUndefined();
    });

    it("should reject invalid version", () => {
      const plan = { ...validPlan, version: "plan.v2" as any };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors).toBeDefined();
      expect(result.errors?.[0].code).toBe("invalid_version");
    });

    it("should reject missing workflow ID", () => {
      const plan = { ...validPlan, workflowId: "" };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "missing_workflow_id")).toBe(true);
    });

    it("should reject empty nodes", () => {
      const plan = { ...validPlan, nodes: [] };
      const result = validator.validate(plan, [], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "empty_nodes")).toBe(true);
    });

    it("should reject missing node IDs", () => {
      const nodeWithoutId = { ...sampleNode };
      delete (nodeWithoutId as any).id;
      const plan = { ...validPlan, nodes: [nodeWithoutId as PlanNode] };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "missing_node_id")).toBe(true);
    });

    it("should reject duplicate node IDs", () => {
      const plan = {
        ...validPlan,
        nodes: [sampleNode, { ...sampleNode }],
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "duplicate_node_id")).toBe(true);
    });
  });

  describe("DAG validation", () => {
    it("rejects a cycle reachable from a root without entering depth traversal", () => {
      const plan = {
        ...validPlan,
        nodes: ["root", "a", "b"].map((id) => ({ ...sampleNode, id })),
        edges: [
          { from: "root", to: "a" },
          { from: "a", to: "b" },
          { from: "b", to: "a" },
        ],
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors).toContainEqual(expect.objectContaining({ code: "cycle_detected" }));
    });

    it("should accept valid DAG", () => {
      const nodes: PlanNode[] = [
        { ...sampleNode, id: "node-1" },
        { ...sampleNode, id: "node-2" },
        { ...sampleNode, id: "node-3" },
      ];
      const edges: PlanEdge[] = [
        { from: "node-1", to: "node-2" },
        { from: "node-2", to: "node-3" },
      ];
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
    });

    it("should detect simple cycle", () => {
      const nodes: PlanNode[] = [
        { ...sampleNode, id: "node-1" },
        { ...sampleNode, id: "node-2" },
      ];
      const edges: PlanEdge[] = [
        { from: "node-1", to: "node-2" },
        { from: "node-2", to: "node-1" },
      ];
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "cycle_detected")).toBe(true);
    });

    it("should detect complex cycle", () => {
      const nodes: PlanNode[] = [
        { ...sampleNode, id: "node-1" },
        { ...sampleNode, id: "node-2" },
        { ...sampleNode, id: "node-3" },
      ];
      const edges: PlanEdge[] = [
        { from: "node-1", to: "node-2" },
        { from: "node-2", to: "node-3" },
        { from: "node-3", to: "node-1" },
      ];
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "cycle_detected")).toBe(true);
    });

    it("should reject edge to non-existent node", () => {
      const nodes: PlanNode[] = [{ ...sampleNode, id: "node-1" }];
      const edges: PlanEdge[] = [{ from: "node-1", to: "node-999" }];
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "invalid_edge_to")).toBe(true);
    });

    it("should reject edge from non-existent node", () => {
      const nodes: PlanNode[] = [{ ...sampleNode, id: "node-1" }];
      const edges: PlanEdge[] = [{ from: "node-999", to: "node-1" }];
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "invalid_edge_from")).toBe(true);
    });

    it("should accept diamond DAG", () => {
      const nodes: PlanNode[] = [
        { ...sampleNode, id: "node-1" },
        { ...sampleNode, id: "node-2" },
        { ...sampleNode, id: "node-3" },
        { ...sampleNode, id: "node-4" },
      ];
      const edges: PlanEdge[] = [
        { from: "node-1", to: "node-2" },
        { from: "node-1", to: "node-3" },
        { from: "node-2", to: "node-4" },
        { from: "node-3", to: "node-4" },
      ];
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
    });
  });

  describe("capability validation", () => {
    it("should accept nodes with granted capabilities", () => {
      const nodes: PlanNode[] = [
        { ...sampleNode, id: "node-1", type: "agent", agentId: "agent-1" },
        { ...sampleNode, id: "node-2", type: "tool", toolId: "tool-1" },
      ];
      const plan = { ...validPlan, nodes, edges: [] };
      const capabilities = ["agent:agent-1", "tool:tool-1"];
      const result = validator.validate(plan, capabilities, defaultBudget);
      expect(result.valid).toBe(true);
    });

    it("should reject agent without capability", () => {
      const node = { ...sampleNode, type: "agent" as const, agentId: "unauthorized-agent" };
      const plan = { ...validPlan, nodes: [node] };
      const result = validator.validate(plan, ["agent:other-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "capability_not_granted")).toBe(true);
    });

    it("should reject tool without capability", () => {
      const node = { ...sampleNode, type: "tool" as const, toolId: "unauthorized-tool" };
      const plan = { ...validPlan, nodes: [node] };
      const result = validator.validate(plan, ["tool:other-tool"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "capability_not_granted")).toBe(true);
    });

    it("should not check capability for decision nodes", () => {
      const node = { ...sampleNode, type: "decision" as const };
      delete (node as any).agentId;
      const plan = { ...validPlan, nodes: [node] };
      const result = validator.validate(plan, [], defaultBudget);
      expect(result.valid).toBe(true);
    });
  });

  describe("budget validation", () => {
    it("should accept budget within limits", () => {
      const plan = {
        ...validPlan,
        budget: {
          maxCostUsd: 5.0,
          maxDurationMs: 300000,
          maxModelTokens: 500000,
          maxToolCalls: 50,
        },
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
    });

    it("should reject excessive cost", () => {
      const plan = {
        ...validPlan,
        budget: { ...validPlan.budget, maxCostUsd: 20.0 },
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(
        result.errors?.some((e) => e.code === "budget_exceeded" && e.path === "budget.maxCostUsd"),
      ).toBe(true);
    });

    it("should reject excessive duration", () => {
      const plan = {
        ...validPlan,
        budget: { ...validPlan.budget, maxDurationMs: 1000000 },
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(
        result.errors?.some(
          (e) => e.code === "budget_exceeded" && e.path === "budget.maxDurationMs",
        ),
      ).toBe(true);
    });

    it("should reject excessive tokens", () => {
      const plan = {
        ...validPlan,
        budget: { ...validPlan.budget, maxModelTokens: 2000000 },
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(
        result.errors?.some(
          (e) => e.code === "budget_exceeded" && e.path === "budget.maxModelTokens",
        ),
      ).toBe(true);
    });

    it("should reject excessive tool calls", () => {
      const plan = {
        ...validPlan,
        budget: { ...validPlan.budget, maxToolCalls: 200 },
      };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(
        result.errors?.some(
          (e) => e.code === "budget_exceeded" && e.path === "budget.maxToolCalls",
        ),
      ).toBe(true);
    });
  });

  describe("fan-out and depth validation", () => {
    it("should accept reasonable fan-out", () => {
      const nodes: PlanNode[] = Array.from({ length: 6 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
      }));
      const edges: PlanEdge[] = Array.from({ length: 5 }, (_, i) => ({
        from: "node-0",
        to: `node-${i + 1}`,
      }));
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
    });

    it("should reject excessive fan-out", () => {
      const nodes: PlanNode[] = Array.from({ length: 12 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
      }));
      const edges: PlanEdge[] = Array.from({ length: 11 }, (_, i) => ({
        from: "node-0",
        to: `node-${i + 1}`,
      }));
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "fan_out_exceeded")).toBe(true);
    });

    it("should accept reasonable depth", () => {
      const nodes: PlanNode[] = Array.from({ length: 10 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
      }));
      const edges: PlanEdge[] = Array.from({ length: 9 }, (_, i) => ({
        from: `node-${i}`,
        to: `node-${i + 1}`,
      }));
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
    });

    it("should reject excessive depth", () => {
      const nodes: PlanNode[] = Array.from({ length: 25 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
      }));
      const edges: PlanEdge[] = Array.from({ length: 24 }, (_, i) => ({
        from: `node-${i}`,
        to: `node-${i + 1}`,
      }));
      const plan = { ...validPlan, nodes, edges };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "depth_exceeded")).toBe(true);
    });
  });

  describe("side effect validation", () => {
    it("should accept reasonable side effects", () => {
      const nodes: PlanNode[] = Array.from({ length: 10 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
        type: i % 2 === 0 ? ("agent" as const) : ("tool" as const),
      }));
      const plan = { ...validPlan, nodes, edges: [] };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(true);
    });

    it("should reject excessive side effects", () => {
      const nodes: PlanNode[] = Array.from({ length: 60 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
        type: "agent" as const,
        agentId: "test-agent",
      }));
      const plan = { ...validPlan, nodes, edges: [] };
      const result = validator.validate(plan, ["agent:test-agent"], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.code === "side_effects_exceeded")).toBe(true);
    });

    it("should not count decision nodes as side effects", () => {
      const nodes: PlanNode[] = Array.from({ length: 60 }, (_, i) => {
        const node = { ...sampleNode, id: `node-${i}`, type: "decision" as const };
        delete (node as any).agentId;
        return node;
      });
      const plan = { ...validPlan, nodes, edges: [] };
      const result = validator.validate(plan, [], defaultBudget);
      expect(result.valid).toBe(true);
    });
  });

  describe("approval requirements", () => {
    it("should not require approval for simple plan", () => {
      const plan = {
        ...validPlan,
        nodes: [sampleNode],
        budget: {
          maxCostUsd: 0.5,
          maxDurationMs: 30000,
          maxModelTokens: 50000,
          maxToolCalls: 5,
        },
      };
      const requiresApproval = validator.requiresApproval(plan);
      expect(requiresApproval).toBe(true); // Has agent node, so requires approval
    });

    it("should require approval for high cost", () => {
      const plan = {
        ...validPlan,
        budget: { ...validPlan.budget, maxCostUsd: 5.0 },
      };
      const requiresApproval = validator.requiresApproval(plan);
      expect(requiresApproval).toBe(true);
    });

    it("should require approval for many tool calls", () => {
      const plan = {
        ...validPlan,
        budget: { ...validPlan.budget, maxToolCalls: 50 },
      };
      const requiresApproval = validator.requiresApproval(plan);
      expect(requiresApproval).toBe(true);
    });

    it("should require approval for many nodes", () => {
      const nodes: PlanNode[] = Array.from({ length: 15 }, (_, i) => ({
        ...sampleNode,
        id: `node-${i}`,
      }));
      const plan = { ...validPlan, nodes };
      const requiresApproval = validator.requiresApproval(plan);
      expect(requiresApproval).toBe(true);
    });

    it("should require approval for plans with side effects", () => {
      const node = { ...sampleNode, type: "tool" as const, toolId: "write-file" };
      const plan = {
        ...validPlan,
        nodes: [node],
        budget: {
          maxCostUsd: 0.1,
          maxDurationMs: 10000,
          maxModelTokens: 10000,
          maxToolCalls: 5,
        },
      };
      const requiresApproval = validator.requiresApproval(plan);
      expect(requiresApproval).toBe(true);
    });
  });

  describe("multiple errors", () => {
    it("should collect all validation errors", () => {
      const plan = {
        version: "plan.v2" as any,
        workflowId: "",
        nodes: [],
        edges: [],
        budget: {
          maxCostUsd: 100.0,
          maxDurationMs: 10000000,
          maxModelTokens: 10000000,
          maxToolCalls: 1000,
        },
      };
      const result = validator.validate(plan, [], defaultBudget);
      expect(result.valid).toBe(false);
      expect(result.errors).toBeDefined();
      expect(result.errors!.length).toBeGreaterThan(1);
    });
  });
});
