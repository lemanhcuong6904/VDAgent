/**
 * Plan Validator
 * Validates workflow plans for DAG structure, capabilities, budget, side effects
 */

import type {
  Budget,
  PlanEdge,
  PlanNode,
  PlanSpec,
  ValidationError,
  ValidationResult,
} from "./workflow-module.js";

export class PlanValidator {
  /**
   * Validate a complete plan specification
   */
  validate(
    plan: PlanSpec,
    availableCapabilities: string[],
    maxAllowedBudget: Budget,
  ): ValidationResult {
    const errors: ValidationError[] = [];

    // Schema validation
    errors.push(...this.validateSchema(plan));

    // DAG structure validation
    const graphErrors = this.validateDAG(plan.nodes, plan.edges);
    errors.push(...graphErrors);

    // Capability validation
    errors.push(...this.validateCapabilities(plan.nodes, availableCapabilities));

    // Budget validation
    errors.push(...this.validateBudget(plan.budget, maxAllowedBudget));

    // Fan-out and depth validation
    // Depth traversal assumes a DAG; a reachable cycle otherwise increases depth forever.
    if (graphErrors.length === 0) {
      errors.push(...this.validateFanOutAndDepth(plan.nodes, plan.edges));
    }

    // Side effect validation
    errors.push(...this.validateSideEffects(plan.nodes));

    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  /**
   * Validate plan schema and required fields
   */
  private validateSchema(plan: PlanSpec): ValidationError[] {
    const errors: ValidationError[] = [];

    if (plan.version !== "plan.v1") {
      errors.push({
        code: "invalid_version",
        message: `Plan version must be 'plan.v1', got '${plan.version}'`,
        path: "version",
      });
    }

    if (!plan.workflowId) {
      errors.push({
        code: "missing_workflow_id",
        message: "Plan must have a workflow ID",
        path: "workflowId",
      });
    }

    if (!Array.isArray(plan.nodes) || plan.nodes.length === 0) {
      errors.push({
        code: "empty_nodes",
        message: "Plan must have at least one node",
        path: "nodes",
      });
    }

    if (!Array.isArray(plan.edges)) {
      errors.push({
        code: "missing_edges",
        message: "Plan must have edges array",
        path: "edges",
      });
    }

    if (!plan.budget) {
      errors.push({
        code: "missing_budget",
        message: "Plan must have budget",
        path: "budget",
      });
    }

    // Validate node IDs are unique and stable
    const nodeIds = new Set<string>();
    for (let i = 0; i < plan.nodes.length; i++) {
      const node = plan.nodes[i];

      if (!node.id) {
        errors.push({
          code: "missing_node_id",
          message: `Node at index ${i} missing ID`,
          path: `nodes[${i}].id`,
        });
      } else if (nodeIds.has(node.id)) {
        errors.push({
          code: "duplicate_node_id",
          message: `Duplicate node ID: ${node.id}`,
          path: `nodes[${i}].id`,
        });
      } else {
        nodeIds.add(node.id);
      }
    }

    return errors;
  }

  /**
   * Validate DAG structure (no cycles)
   */
  private validateDAG(nodes: PlanNode[], edges: PlanEdge[]): ValidationError[] {
    const errors: ValidationError[] = [];

    // Build adjacency list
    const adjacency = new Map<string, string[]>();
    const nodeIds = new Set(nodes.map((n) => n.id));

    for (const edge of edges) {
      // Validate edge references exist
      if (!nodeIds.has(edge.from)) {
        errors.push({
          code: "invalid_edge_from",
          message: `Edge references non-existent node: ${edge.from}`,
          path: "edges",
        });
        continue;
      }

      if (!nodeIds.has(edge.to)) {
        errors.push({
          code: "invalid_edge_to",
          message: `Edge references non-existent node: ${edge.to}`,
          path: "edges",
        });
        continue;
      }

      if (!adjacency.has(edge.from)) {
        adjacency.set(edge.from, []);
      }
      const neighbors = adjacency.get(edge.from);
      if (!neighbors) throw new Error(`Failed to initialize outgoing edges for ${edge.from}`);
      neighbors.push(edge.to);
    }

    // Detect cycles using DFS
    const visited = new Set<string>();
    const recursionStack = new Set<string>();

    const hasCycle = (nodeId: string): boolean => {
      visited.add(nodeId);
      recursionStack.add(nodeId);

      const neighbors = adjacency.get(nodeId) || [];
      for (const neighbor of neighbors) {
        if (!visited.has(neighbor)) {
          if (hasCycle(neighbor)) {
            return true;
          }
        } else if (recursionStack.has(neighbor)) {
          return true;
        }
      }

      recursionStack.delete(nodeId);
      return false;
    };

    for (const nodeId of nodeIds) {
      if (!visited.has(nodeId)) {
        if (hasCycle(nodeId)) {
          errors.push({
            code: "cycle_detected",
            message: "Plan contains a cycle - must be a DAG",
            path: "edges",
          });
          break;
        }
      }
    }

    return errors;
  }

  /**
   * Validate nodes use only available capabilities
   */
  private validateCapabilities(
    nodes: PlanNode[],
    availableCapabilities: string[],
  ): ValidationError[] {
    const errors: ValidationError[] = [];
    const capabilitySet = new Set(availableCapabilities);

    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];

      if (node.type === "agent" && node.agentId) {
        // Agent nodes require agent capability
        if (!capabilitySet.has(`agent:${node.agentId}`)) {
          errors.push({
            code: "capability_not_granted",
            message: `Agent ${node.agentId} not in available capabilities`,
            path: `nodes[${i}].agentId`,
          });
        }
      }

      if (node.type === "tool" && node.toolId) {
        // Tool nodes require tool capability
        if (!capabilitySet.has(`tool:${node.toolId}`)) {
          errors.push({
            code: "capability_not_granted",
            message: `Tool ${node.toolId} not in available capabilities`,
            path: `nodes[${i}].toolId`,
          });
        }
      }
    }

    return errors;
  }

  /**
   * Validate budget constraints
   */
  private validateBudget(budget: Budget, maxAllowed: Budget): ValidationError[] {
    const errors: ValidationError[] = [];

    if (budget.maxCostUsd > maxAllowed.maxCostUsd) {
      errors.push({
        code: "budget_exceeded",
        message: `Cost ${budget.maxCostUsd} exceeds limit ${maxAllowed.maxCostUsd}`,
        path: "budget.maxCostUsd",
      });
    }

    if (budget.maxDurationMs > maxAllowed.maxDurationMs) {
      errors.push({
        code: "budget_exceeded",
        message: `Duration ${budget.maxDurationMs} exceeds limit ${maxAllowed.maxDurationMs}`,
        path: "budget.maxDurationMs",
      });
    }

    if (budget.maxModelTokens > maxAllowed.maxModelTokens) {
      errors.push({
        code: "budget_exceeded",
        message: `Tokens ${budget.maxModelTokens} exceeds limit ${maxAllowed.maxModelTokens}`,
        path: "budget.maxModelTokens",
      });
    }

    if (budget.maxToolCalls > maxAllowed.maxToolCalls) {
      errors.push({
        code: "budget_exceeded",
        message: `Tool calls ${budget.maxToolCalls} exceeds limit ${maxAllowed.maxToolCalls}`,
        path: "budget.maxToolCalls",
      });
    }

    return errors;
  }

  /**
   * Validate fan-out and depth limits
   */
  private validateFanOutAndDepth(nodes: PlanNode[], edges: PlanEdge[]): ValidationError[] {
    const errors: ValidationError[] = [];

    // Build adjacency for depth calculation
    const adjacency = new Map<string, string[]>();
    for (const edge of edges) {
      if (!adjacency.has(edge.from)) {
        adjacency.set(edge.from, []);
      }
      const neighbors = adjacency.get(edge.from);
      if (!neighbors) throw new Error(`Failed to initialize outgoing edges for ${edge.from}`);
      neighbors.push(edge.to);
    }

    // Check fan-out (max children per node)
    const maxFanOut = 10;
    for (const [nodeId, children] of adjacency.entries()) {
      if (children.length > maxFanOut) {
        errors.push({
          code: "fan_out_exceeded",
          message: `Node ${nodeId} has ${children.length} children, max ${maxFanOut}`,
          path: "edges",
        });
      }
    }

    // Calculate max depth using BFS
    const depths = new Map<string, number>();
    const queue: Array<{ id: string; depth: number }> = [];

    // Find root nodes (no incoming edges)
    const hasIncoming = new Set<string>();
    for (const edge of edges) {
      hasIncoming.add(edge.to);
    }

    for (const node of nodes) {
      if (!hasIncoming.has(node.id)) {
        queue.push({ id: node.id, depth: 0 });
        depths.set(node.id, 0);
      }
    }

    let maxDepth = 0;
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current) break;
      const { id, depth } = current;
      maxDepth = Math.max(maxDepth, depth);

      const children = adjacency.get(id) || [];
      for (const childId of children) {
        const childDepth = depth + 1;
        const currentDepth = depths.get(childId) ?? -1;

        if (childDepth > currentDepth) {
          depths.set(childId, childDepth);
          queue.push({ id: childId, depth: childDepth });
        }
      }
    }

    const maxAllowedDepth = 20;
    if (maxDepth > maxAllowedDepth) {
      errors.push({
        code: "depth_exceeded",
        message: `Plan depth ${maxDepth} exceeds limit ${maxAllowedDepth}`,
        path: "nodes",
      });
    }

    return errors;
  }

  /**
   * Validate side effect constraints
   */
  private validateSideEffects(nodes: PlanNode[]): ValidationError[] {
    const errors: ValidationError[] = [];

    // Count nodes with side effects
    let sideEffectCount = 0;
    for (const node of nodes) {
      if (node.type === "tool" || node.type === "agent") {
        sideEffectCount++;
      }
    }

    // Limit side-effect operations
    const maxSideEffects = 50;
    if (sideEffectCount > maxSideEffects) {
      errors.push({
        code: "side_effects_exceeded",
        message: `Plan has ${sideEffectCount} side-effect nodes, max ${maxSideEffects}`,
        path: "nodes",
      });
    }

    return errors;
  }

  /**
   * Check if plan requires approval
   */
  requiresApproval(plan: PlanSpec): boolean {
    // Plans with high cost require approval
    if (plan.budget.maxCostUsd > 1.0) {
      return true;
    }

    // Plans with many tool calls require approval
    if (plan.budget.maxToolCalls > 20) {
      return true;
    }

    // Plans with many nodes require approval
    if (plan.nodes.length > 10) {
      return true;
    }

    // Plans with write/delete/execute side effects require approval
    const hasSideEffects = plan.nodes.some((node) => node.type === "tool" || node.type === "agent");

    if (hasSideEffects) {
      return true;
    }

    return false;
  }
}
