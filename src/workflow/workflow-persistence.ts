/**
 * Workflow Persistence
 * Persist parent/child/step/checkpoint/usage/event with manifest/policy pin
 */

import type { AgentScope } from "../contracts/index.js";
import type { NodeCheckpoint } from "./node-lifecycle.js";
import type {
  CheckpointRef,
  PlanSpec,
  UsageSummary,
  WorkflowError,
  WorkflowEvent,
  WorkflowManifest,
} from "./workflow-module.js";

/**
 * Workflow execution record
 */
export interface WorkflowExecution {
  workflowId: string;
  runId: string;
  parentRunId?: string;
  scope: AgentScope;
  status: "pending" | "running" | "waiting" | "completed" | "failed" | "cancelled";
  manifest: WorkflowManifest;
  manifestHash: string;
  plan?: PlanSpec;
  planHash?: string;
  startedAt: string;
  completedAt?: string;
  input?: unknown;
  output?: unknown;
  usage: UsageSummary;
  checkpoints: CheckpointRef[];
  events: WorkflowEvent[];
  errors: WorkflowError[];
  metadata?: Record<string, unknown>;
}

/**
 * Workflow step record (node execution within workflow)
 */
export interface WorkflowStep {
  stepId: string;
  runId: string;
  nodeId: string;
  parentStepId?: string;
  attemptId: string;
  status: "pending" | "running" | "checkpoint" | "waiting" | "completed" | "failed" | "cancelled";
  startedAt: string;
  completedAt?: string;
  input?: unknown;
  output?: unknown;
  error?: WorkflowError;
  durationMs?: number;
  costUsd?: number;
  checkpoints: NodeCheckpoint[];
  metadata?: Record<string, unknown>;
}

/**
 * Workflow parent-child relationship
 */
export interface WorkflowRelationship {
  parentRunId: string;
  childRunId: string;
  parentStepId?: string;
  relationshipType: "subworkflow" | "parallel" | "continuation";
  createdAt: string;
}

/**
 * Persisted checkpoint with full state
 */
export interface PersistedCheckpoint {
  id: string;
  runId: string;
  nodeId?: string;
  stepId?: string;
  timestamp: string;
  state: unknown;
  stateHash: string;
  manifestHash: string;
  planHash?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Workflow event log entry
 */
export interface WorkflowEventLog {
  eventId: string;
  runId: string;
  stepId?: string;
  nodeId?: string;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
  severity: "debug" | "info" | "warning" | "error";
}

/**
 * Usage tracking record
 */
export interface UsageRecord {
  runId: string;
  stepId?: string;
  timestamp: string;
  durationMs: number;
  costUsd?: number;
  modelTokens?: number;
  toolCalls?: number;
  metadata?: Record<string, unknown>;
}

/**
 * Manifest pinning for replay
 */
export interface ManifestPin {
  hash: string;
  manifest: WorkflowManifest | PlanSpec;
  pinnedAt: string;
  usageCount: number;
}

/**
 * Workflow persistence layer
 */
export class WorkflowPersistence {
  private executions: Map<string, WorkflowExecution> = new Map();
  private steps: Map<string, WorkflowStep> = new Map();
  private relationships: Map<string, WorkflowRelationship[]> = new Map();
  private checkpoints: Map<string, PersistedCheckpoint> = new Map();
  private events: Map<string, WorkflowEventLog[]> = new Map();
  private usageRecords: Map<string, UsageRecord[]> = new Map();
  private manifestPins: Map<string, ManifestPin> = new Map();

  /**
   * Create a new workflow execution record
   */
  async createExecution(
    workflowId: string,
    runId: string,
    manifest: WorkflowManifest,
    scope: AgentScope,
    input?: unknown,
    parentRunId?: string,
  ): Promise<WorkflowExecution> {
    const manifestHash = this.hashObject(manifest);
    await this.pinManifest(manifestHash, manifest);

    const execution: WorkflowExecution = {
      workflowId,
      runId,
      parentRunId,
      scope,
      status: "pending",
      manifest,
      manifestHash,
      startedAt: new Date().toISOString(),
      input,
      usage: {
        durationMs: 0,
        costUsd: 0,
        modelTokens: 0,
        toolCalls: 0,
        nodesExecuted: 0,
      },
      checkpoints: [],
      events: [],
      errors: [],
    };

    this.executions.set(runId, execution);

    // Record parent-child relationship
    if (parentRunId) {
      await this.recordRelationship({
        parentRunId,
        childRunId: runId,
        relationshipType: "subworkflow",
        createdAt: execution.startedAt,
      });
    }

    await this.recordEvent({
      eventId: this.generateId(),
      runId,
      type: "workflow.created",
      timestamp: execution.startedAt,
      data: { workflowId, manifestHash },
      severity: "info",
    });

    return execution;
  }

  /**
   * Update workflow execution plan
   */
  async updatePlan(runId: string, plan: PlanSpec): Promise<void> {
    const execution = this.executions.get(runId);
    if (!execution) {
      throw new Error(`Workflow execution ${runId} not found`);
    }

    const planHash = this.hashObject(plan);
    await this.pinManifest(planHash, plan);

    execution.plan = plan;
    execution.planHash = planHash;

    await this.recordEvent({
      eventId: this.generateId(),
      runId,
      type: "workflow.plan_updated",
      timestamp: new Date().toISOString(),
      data: { planHash, nodeCount: plan.nodes.length },
      severity: "info",
    });
  }

  /**
   * Update workflow execution status
   */
  async updateExecutionStatus(
    runId: string,
    status: WorkflowExecution["status"],
    output?: unknown,
    error?: WorkflowError,
  ): Promise<void> {
    const execution = this.executions.get(runId);
    if (!execution) {
      throw new Error(`Workflow execution ${runId} not found`);
    }

    const previousStatus = execution.status;
    execution.status = status;

    if (output !== undefined) {
      execution.output = output;
    }

    if (error) {
      execution.errors.push(error);
    }

    if (status === "completed" || status === "failed" || status === "cancelled") {
      execution.completedAt = new Date().toISOString();
    }

    await this.recordEvent({
      eventId: this.generateId(),
      runId,
      type: `workflow.${status}`,
      timestamp: new Date().toISOString(),
      data: { previousStatus, status, hasError: !!error },
      severity: error ? "error" : "info",
    });
  }

  /**
   * Create a workflow step record
   */
  async createStep(
    runId: string,
    nodeId: string,
    attemptId: string,
    input?: unknown,
    parentStepId?: string,
  ): Promise<WorkflowStep> {
    const stepId = this.generateId();

    const step: WorkflowStep = {
      stepId,
      runId,
      nodeId,
      parentStepId,
      attemptId,
      status: "pending",
      startedAt: new Date().toISOString(),
      input,
      checkpoints: [],
    };

    this.steps.set(stepId, step);

    const execution = this.executions.get(runId);
    if (execution) {
      execution.usage.nodesExecuted++;
    }

    await this.recordEvent({
      eventId: this.generateId(),
      runId,
      stepId,
      nodeId,
      type: "step.created",
      timestamp: step.startedAt,
      data: { nodeId, attemptId, parentStepId },
      severity: "debug",
    });

    return step;
  }

  /**
   * Update step status
   */
  async updateStepStatus(
    stepId: string,
    status: WorkflowStep["status"],
    output?: unknown,
    error?: WorkflowError,
    durationMs?: number,
    costUsd?: number,
  ): Promise<void> {
    const step = this.steps.get(stepId);
    if (!step) {
      throw new Error(`Workflow step ${stepId} not found`);
    }

    step.status = status;

    if (output !== undefined) {
      step.output = output;
    }

    if (error) {
      step.error = error;
    }

    if (durationMs !== undefined) {
      step.durationMs = durationMs;
    }

    if (costUsd !== undefined) {
      step.costUsd = costUsd;
    }

    if (status === "completed" || status === "failed" || status === "cancelled") {
      step.completedAt = new Date().toISOString();

      // Record usage
      await this.recordUsage({
        runId: step.runId,
        stepId,
        timestamp: step.completedAt,
        durationMs: step.durationMs || 0,
        costUsd: step.costUsd,
      });
    }

    await this.recordEvent({
      eventId: this.generateId(),
      runId: step.runId,
      stepId,
      nodeId: step.nodeId,
      type: `step.${status}`,
      timestamp: new Date().toISOString(),
      data: { status, hasError: !!error },
      severity: error ? "error" : "debug",
    });
  }

  /**
   * Persist a checkpoint
   */
  async persistCheckpoint(
    runId: string,
    state: unknown,
    nodeId?: string,
    stepId?: string,
  ): Promise<PersistedCheckpoint> {
    const execution = this.executions.get(runId);
    if (!execution) {
      throw new Error(`Workflow execution ${runId} not found`);
    }

    const checkpoint: PersistedCheckpoint = {
      id: this.generateId(),
      runId,
      nodeId,
      stepId,
      timestamp: new Date().toISOString(),
      state,
      stateHash: this.hashObject(state),
      manifestHash: execution.manifestHash,
      planHash: execution.planHash,
    };

    this.checkpoints.set(checkpoint.id, checkpoint);

    // Add to execution checkpoint refs
    const checkpointRef: CheckpointRef = {
      id: checkpoint.id,
      nodeId: nodeId || "",
      timestamp: checkpoint.timestamp,
      stateHash: checkpoint.stateHash,
    };
    execution.checkpoints.push(checkpointRef);

    await this.recordEvent({
      eventId: this.generateId(),
      runId,
      stepId,
      nodeId,
      type: "checkpoint.created",
      timestamp: checkpoint.timestamp,
      data: { checkpointId: checkpoint.id, stateHash: checkpoint.stateHash },
      severity: "debug",
    });

    return checkpoint;
  }

  /**
   * Record parent-child relationship
   */
  async recordRelationship(relationship: WorkflowRelationship): Promise<void> {
    const key = relationship.parentRunId;
    if (!this.relationships.has(key)) {
      this.relationships.set(key, []);
    }
    const relationships = this.relationships.get(key);
    if (!relationships) throw new Error(`Failed to initialize relationships for run ${key}`);
    relationships.push(relationship);
  }

  /**
   * Record an event
   */
  async recordEvent(event: WorkflowEventLog): Promise<void> {
    if (!this.events.has(event.runId)) {
      this.events.set(event.runId, []);
    }
    const events = this.events.get(event.runId);
    if (!events) throw new Error(`Failed to initialize events for run ${event.runId}`);
    events.push(event);

    const execution = this.executions.get(event.runId);
    if (execution) {
      execution.events.push({
        id: event.eventId,
        type: event.type,
        timestamp: event.timestamp,
        nodeId: event.nodeId,
        data: event.data,
      });
    }
  }

  /**
   * Record usage
   */
  async recordUsage(usage: UsageRecord): Promise<void> {
    if (!this.usageRecords.has(usage.runId)) {
      this.usageRecords.set(usage.runId, []);
    }
    const records = this.usageRecords.get(usage.runId);
    if (!records) throw new Error(`Failed to initialize usage records for run ${usage.runId}`);
    records.push(usage);

    // Update execution usage
    const execution = this.executions.get(usage.runId);
    if (execution) {
      execution.usage.durationMs += usage.durationMs;
      if (usage.costUsd) {
        execution.usage.costUsd += usage.costUsd;
      }
      if (usage.modelTokens) {
        execution.usage.modelTokens += usage.modelTokens;
      }
      if (usage.toolCalls) {
        execution.usage.toolCalls += usage.toolCalls;
      }
    }
  }

  /**
   * Pin a manifest for replay
   */
  async pinManifest(hash: string, manifest: WorkflowManifest | PlanSpec): Promise<void> {
    const existing = this.manifestPins.get(hash);
    if (existing) {
      existing.usageCount++;
    } else {
      this.manifestPins.set(hash, {
        hash,
        manifest,
        pinnedAt: new Date().toISOString(),
        usageCount: 1,
      });
    }
  }

  /**
   * Get workflow execution
   */
  getExecution(runId: string): WorkflowExecution | undefined {
    return this.executions.get(runId);
  }

  /**
   * Get workflow step
   */
  getStep(stepId: string): WorkflowStep | undefined {
    return this.steps.get(stepId);
  }

  /**
   * Get all steps for a run
   */
  getSteps(runId: string): WorkflowStep[] {
    return Array.from(this.steps.values()).filter((step) => step.runId === runId);
  }

  /**
   * Get checkpoint
   */
  getCheckpoint(checkpointId: string): PersistedCheckpoint | undefined {
    return this.checkpoints.get(checkpointId);
  }

  /**
   * Get all checkpoints for a run
   */
  getCheckpoints(runId: string): PersistedCheckpoint[] {
    return Array.from(this.checkpoints.values()).filter((cp) => cp.runId === runId);
  }

  /**
   * Get child workflows
   */
  getChildren(parentRunId: string): WorkflowRelationship[] {
    return this.relationships.get(parentRunId) || [];
  }

  /**
   * Get events for a run
   */
  getEvents(runId: string): WorkflowEventLog[] {
    return this.events.get(runId) || [];
  }

  /**
   * Get usage records for a run
   */
  getUsageRecords(runId: string): UsageRecord[] {
    return this.usageRecords.get(runId) || [];
  }

  /**
   * Get pinned manifest
   */
  getPinnedManifest(hash: string): ManifestPin | undefined {
    return this.manifestPins.get(hash);
  }

  /**
   * Get execution summary
   */
  getExecutionSummary(runId: string): WorkflowExecutionSummary | undefined {
    const execution = this.executions.get(runId);
    if (!execution) {
      return undefined;
    }

    const steps = this.getSteps(runId);
    const children = this.getChildren(runId);
    const checkpoints = this.getCheckpoints(runId);

    return {
      runId: execution.runId,
      workflowId: execution.workflowId,
      status: execution.status,
      startedAt: execution.startedAt,
      completedAt: execution.completedAt,
      usage: execution.usage,
      stepCount: steps.length,
      checkpointCount: checkpoints.length,
      childCount: children.length,
      errorCount: execution.errors.length,
      hasOutput: execution.output !== undefined,
    };
  }

  private hashObject(obj: unknown): string {
    const json = JSON.stringify(obj);
    let hash = 0;
    for (let i = 0; i < json.length; i++) {
      const char = json.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash = hash & hash;
    }
    return hash.toString(36);
  }

  private generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
  }
}

export interface WorkflowExecutionSummary {
  runId: string;
  workflowId: string;
  status: WorkflowExecution["status"];
  startedAt: string;
  completedAt?: string;
  usage: UsageSummary;
  stepCount: number;
  checkpointCount: number;
  childCount: number;
  errorCount: number;
  hasOutput: boolean;
}
