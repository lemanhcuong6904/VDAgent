/**
 * Workflow Module and Plan Specification
 * Interface-first workflow definition with typed state and stable node IDs
 */

import type { AgentScope } from "../contracts/index.js";

/**
 * Workflow module with typed state and execute function
 */
export interface WorkflowModule<S = unknown, O = unknown> {
  manifest: WorkflowManifest;
  execute(ctx: WorkflowContext<S>): Promise<WorkflowResult<O>>;
}

export interface WorkflowManifest {
  apiVersion: "workflow.v1";
  id: string;
  version: string;
  displayName: string;
  description: string;
  stateSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  capabilities: string[];
  requiredPorts: string[];
  limits: WorkflowLimits;
  tags?: string[];
}

export interface WorkflowLimits {
  maxNodes: number;
  maxDepth: number;
  maxFanOut: number;
  maxDurationMs: number;
  maxCostUsd: number;
  requiresApproval: boolean;
}

export interface WorkflowContext<S = unknown> {
  workflowId: string;
  runId: string;
  attemptId: string;
  scope: AgentScope;
  state: S;
  ports: WorkflowPorts;
  signal: AbortSignal;
  deadline: number;
  emit(event: WorkflowEvent): Promise<void>;
  checkpoint(state: S): Promise<CheckpointRef>;
  wait(reason: WaitRequest): Promise<never>;
}

export interface WorkflowPorts {
  planner: PlannerPort;
  executor: ExecutorPort;
  // Will expand with model, tools, etc. as needed
}

export interface PlannerPort {
  propose(request: PlanRequest): Promise<PlanSpec>;
  validate(plan: PlanSpec): Promise<ValidationResult>;
}

export interface ExecutorPort {
  execute(node: PlanNode, input: unknown): Promise<NodeResult>;
  getStatus(nodeId: string): Promise<NodeStatus | undefined>;
}

/**
 * Plan specification - proposed by planner, validated/approved by host
 */
export interface PlanSpec {
  version: "plan.v1";
  workflowId: string;
  nodes: PlanNode[];
  edges: PlanEdge[];
  budget: Budget;
  metadata?: Record<string, unknown>;
}

export interface PlanNode {
  id: string; // Stable identifier
  type: "agent" | "tool" | "decision" | "parallel" | "sequence";
  displayName: string;
  agentId?: string;
  agentVersion?: string;
  toolId?: string;
  toolVersion?: string;
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  timeout: number;
  retryPolicy: RetryPolicy;
  compensationNode?: string; // Node ID for compensation/rollback
  checkpointBoundary: boolean;
  metadata?: Record<string, unknown>;
}

export interface PlanEdge {
  from: string; // Node ID
  to: string; // Node ID
  condition?: EdgeCondition;
}

export interface EdgeCondition {
  type: "success" | "error" | "timeout" | "custom";
  expression?: string; // For custom conditions
}

export interface RetryPolicy {
  class: "none" | "transient" | "all";
  maxAttempts: number;
  backoffMs: number;
}

export interface Budget {
  maxCostUsd: number;
  maxDurationMs: number;
  maxModelTokens: number;
  maxToolCalls: number;
}

export interface PlanRequest {
  goal: string;
  constraints?: string[];
  availableCapabilities: string[];
  scope: AgentScope;
  budget: Budget;
}

export interface ValidationResult {
  valid: boolean;
  errors?: ValidationError[];
  warnings?: string[];
}

export interface ValidationError {
  code: string;
  message: string;
  path?: string; // JSON path to problematic element
}

/**
 * Workflow execution results
 */
export interface WorkflowResult<O = unknown> {
  status: "completed" | "waiting" | "needs_approval" | "failed";
  output?: O;
  state?: unknown;
  usage: UsageSummary;
  checkpoints: CheckpointRef[];
  events: WorkflowEvent[];
  errors?: WorkflowError[];
}

export interface UsageSummary {
  durationMs: number;
  costUsd: number;
  modelTokens: number;
  toolCalls: number;
  nodesExecuted: number;
}

export interface CheckpointRef {
  id: string;
  nodeId: string;
  timestamp: string;
  stateHash: string;
}

export interface WorkflowEvent {
  id: string;
  type: string;
  timestamp: string;
  nodeId?: string;
  data: Record<string, unknown>;
}

export interface WaitRequest {
  reason: "input" | "approval" | "children" | "tool" | "peer";
  message: string;
  timeoutMs?: number;
}

export interface WorkflowError {
  code: string;
  message: string;
  nodeId?: string;
  retryable: boolean;
}

/**
 * Node execution status and results
 */
export type NodeStatus =
  | "pending"
  | "running"
  | "checkpoint"
  | "waiting"
  | "completed"
  | "failed"
  | "cancelled"
  | "replanning";

export interface NodeResult {
  status: NodeStatus;
  output?: unknown;
  error?: WorkflowError;
  usage: {
    durationMs: number;
    costUsd?: number;
  };
}
