/**
 * Workflow Planner
 * Proposes plans but does not execute - host is authority for schedule/approval
 */

import type { AgentScope } from "../contracts/index.js";
import type {
  Budget,
  PlanEdge,
  PlanNode,
  PlanSpec,
  WorkflowContext,
  WorkflowManifest,
} from "./workflow-module.js";

/**
 * Plan proposal from planner
 */
export interface PlanProposal {
  proposalId: string;
  workflowId: string;
  runId: string;
  /** Host-bound scope of the planning request; the host authority carries it forward. */
  scope: AgentScope;
  plan: PlanSpec;
  rationale: string;
  estimatedCost: number;
  estimatedDuration: number;
  riskLevel: "low" | "medium" | "high";
  requiresApproval: boolean;
  proposedAt: string;
  proposedBy: "system" | "agent" | "user";
}

/**
 * Planning request
 */
export interface PlanningRequest {
  workflowId: string;
  runId: string;
  manifest: WorkflowManifest;
  scope: AgentScope;
  input: unknown;
  context: WorkflowContext;
  constraints?: PlanningConstraints;
}

/**
 * Planning constraints
 */
export interface PlanningConstraints {
  maxNodes?: number;
  maxDepth?: number;
  maxCost?: number;
  maxDuration?: number;
  preferredStrategy?: "sequential" | "parallel" | "adaptive";
  avoidCapabilities?: string[];
  requiredCapabilities?: string[];
}

/**
 * Planning result
 */
export interface PlanningResult {
  success: boolean;
  proposal?: PlanProposal;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
}

/**
 * Planner interface - proposes plans without executing
 */
export interface IPlanner {
  /**
   * Propose a plan for workflow execution
   */
  proposePlan(request: PlanningRequest): Promise<PlanningResult>;

  /**
   * Revise an existing plan based on feedback
   */
  revisePlan(
    proposalId: string,
    feedback: string,
    constraints?: PlanningConstraints,
  ): Promise<PlanningResult>;

  /**
   * Get proposal by ID
   */
  getProposal(proposalId: string): PlanProposal | undefined;
}

/**
 * Basic planner implementation
 * Creates simple sequential or parallel plans based on manifest
 */
export class BasicPlanner implements IPlanner {
  private proposals: Map<string, PlanProposal> = new Map();

  async proposePlan(request: PlanningRequest): Promise<PlanningResult> {
    try {
      // Generate plan based on manifest and constraints
      const plan = this.generatePlan(request);

      // Estimate cost and duration
      const estimation = this.estimateExecution(plan);

      // Determine risk level and approval requirement
      const riskLevel = this.assessRisk(estimation);
      const requiresApproval = this.shouldRequireApproval(
        plan,
        estimation,
        riskLevel,
        request.manifest,
      );

      const proposal: PlanProposal = {
        proposalId: this.generateId(),
        workflowId: request.workflowId,
        runId: request.runId,
        scope: request.scope,
        plan,
        rationale: this.generateRationale(plan, request),
        estimatedCost: estimation.cost,
        estimatedDuration: estimation.duration,
        riskLevel,
        requiresApproval,
        proposedAt: new Date().toISOString(),
        proposedBy: "system",
      };

      this.proposals.set(proposal.proposalId, proposal);

      return {
        success: true,
        proposal,
      };
    } catch (error) {
      return {
        success: false,
        error: {
          code: "planning_failed",
          message: error instanceof Error ? error.message : "Unknown error",
          details: error,
        },
      };
    }
  }

  async revisePlan(
    proposalId: string,
    _feedback: string,
    constraints?: PlanningConstraints,
  ): Promise<PlanningResult> {
    const original = this.proposals.get(proposalId);
    if (!original) {
      return {
        success: false,
        error: {
          code: "proposal_not_found",
          message: `Proposal ${proposalId} not found`,
        },
      };
    }

    // For basic planner, just create a new proposal with updated constraints
    // In production, would use LLM to interpret feedback and adjust plan
    return this.proposePlan({
      workflowId: original.workflowId,
      runId: original.runId,
      manifest: { id: original.workflowId } as WorkflowManifest,
      scope: original.scope,
      input: {},
      context: {} as WorkflowContext,
      constraints,
    });
  }

  getProposal(proposalId: string): PlanProposal | undefined {
    return this.proposals.get(proposalId);
  }

  private generatePlan(request: PlanningRequest): PlanSpec {
    const { manifest, constraints } = request;
    const strategy = constraints?.preferredStrategy || "sequential";

    // Create nodes for each required capability
    const nodes: PlanNode[] = [];
    const edges: PlanEdge[] = [];

    const capabilities = manifest.capabilities || [];
    const maxNodes = Math.min(
      capabilities.length,
      constraints?.maxNodes || manifest.limits?.maxNodes || 10,
    );

    for (let i = 0; i < maxNodes; i++) {
      const capability = capabilities[i];
      if (!capability) break;

      const node: PlanNode = {
        id: `node-${i + 1}`,
        type: capability.startsWith("agent:") ? "agent" : "tool",
        displayName: `${capability} node`,
        agentId: capability.replace("agent:", ""),
        inputSchema: {},
        outputSchema: {},
        timeout: 30000,
        retryPolicy: {
          class: "transient",
          maxAttempts: 3,
          backoffMs: 1000,
        },
        checkpointBoundary: i % 3 === 0, // Checkpoint every 3 nodes
      };

      nodes.push(node);

      // Create edges based on strategy
      if (strategy === "sequential" && i > 0) {
        edges.push({
          from: `node-${i}`,
          to: `node-${i + 1}`,
          condition: undefined,
        });
      }
      // Parallel strategy has no edges (all run in parallel)
    }

    // Calculate budget
    const costPerNode = 0.01; // Rough estimate
    const durationPerNode = 5000; // 5 seconds per node

    const budget: Budget = {
      maxCostUsd: constraints?.maxCost || nodes.length * costPerNode,
      maxDurationMs: constraints?.maxDuration || nodes.length * durationPerNode,
      maxModelTokens: nodes.length * 10000,
      maxToolCalls: nodes.length * 5,
    };

    return {
      version: "plan.v1",
      workflowId: manifest.id,
      nodes,
      edges,
      budget,
    };
  }

  private estimateExecution(plan: PlanSpec): { cost: number; duration: number } {
    const nodeCount = plan.nodes.length;
    const hasParallelism = plan.edges.length < nodeCount - 1;

    // Rough estimates
    const costPerNode = 0.01;
    const durationPerNode = 5000;

    const cost = nodeCount * costPerNode;
    const duration = hasParallelism
      ? durationPerNode * Math.ceil(nodeCount / 3) // Assume 3-way parallelism
      : durationPerNode * nodeCount;

    return { cost, duration };
  }

  private assessRisk(estimation: { cost: number; duration: number }): "low" | "medium" | "high" {
    if (estimation.cost > 1.0 || estimation.duration > 300000) {
      return "high";
    }
    if (estimation.cost > 0.5 || estimation.duration > 120000) {
      return "medium";
    }
    return "low";
  }

  private shouldRequireApproval(
    plan: PlanSpec,
    estimation: { cost: number; duration: number },
    riskLevel: string,
    manifest: WorkflowManifest,
  ): boolean {
    // Require approval if manifest says so
    if (manifest.limits?.requiresApproval) {
      return true;
    }

    // Require approval for high risk
    if (riskLevel === "high") {
      return true;
    }

    // Require approval for expensive or long-running workflows
    if (estimation.cost > 0.5 || estimation.duration > 180000) {
      return true;
    }

    // Require approval for complex plans
    if (plan.nodes.length > 10 || this.calculateDepth(plan) > 5) {
      return true;
    }

    return false;
  }

  private calculateDepth(plan: PlanSpec): number {
    // Simple depth calculation - would use graph traversal in production
    const hasChildren = new Set(plan.edges.map((e) => e.from));
    const roots = plan.nodes.filter((n) => !hasChildren.has(n.id));
    return roots.length > 0 ? Math.ceil(plan.nodes.length / roots.length) : 1;
  }

  private generateRationale(plan: PlanSpec, request: PlanningRequest): string {
    const strategy = plan.edges.length === plan.nodes.length - 1 ? "sequential" : "parallel";
    return (
      `Generated ${strategy} plan with ${plan.nodes.length} nodes for workflow ${request.workflowId}. ` +
      `Estimated cost: $${plan.budget.maxCostUsd.toFixed(3)}, ` +
      `duration: ${(plan.budget.maxDurationMs / 1000).toFixed(0)}s.`
    );
  }

  private generateId(): string {
    return `proposal-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
  }
}
