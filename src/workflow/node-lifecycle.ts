/**
 * Node Lifecycle Manager
 * Manages node execution states and transitions
 */

import type { NodeStatus, WorkflowError } from "./workflow-module.js";

export interface NodeExecution {
  nodeId: string;
  runId: string;
  attemptId: string;
  status: NodeStatus;
  startedAt?: string;
  completedAt?: string;
  input?: unknown;
  output?: unknown;
  error?: WorkflowError;
  checkpoints: NodeCheckpoint[];
  attempts: NodeAttempt[];
  metadata?: Record<string, unknown>;
}

export interface NodeCheckpoint {
  id: string;
  nodeId: string;
  timestamp: string;
  state: unknown;
  stateHash: string;
}

export interface NodeAttempt {
  attemptId: string;
  startedAt: string;
  completedAt?: string;
  status: NodeStatus;
  error?: WorkflowError;
  durationMs?: number;
}

export interface StartNodeRequest {
  nodeId: string;
  runId: string;
  attemptId: string;
  input: unknown;
}

export interface CheckpointNodeRequest {
  nodeId: string;
  runId: string;
  state: unknown;
}

export interface WaitNodeRequest {
  nodeId: string;
  runId: string;
  reason: "input" | "approval" | "children" | "tool" | "peer";
  message: string;
  timeoutMs?: number;
}

export interface ResumeNodeRequest {
  nodeId: string;
  runId: string;
  attemptId: string;
  input?: unknown;
}

export interface CompleteNodeRequest {
  nodeId: string;
  runId: string;
  attemptId: string;
  output: unknown;
  usage: {
    durationMs: number;
    costUsd?: number;
  };
}

export interface FailNodeRequest {
  nodeId: string;
  runId: string;
  attemptId: string;
  error: WorkflowError;
  usage: {
    durationMs: number;
    costUsd?: number;
  };
}

export interface CancelNodeRequest {
  nodeId: string;
  runId: string;
  reason: string;
}

export interface ReplanRequest {
  nodeId: string;
  runId: string;
  reason: string;
  newPlanRequired: boolean;
}

/**
 * Manages node lifecycle and state transitions
 */
export class NodeLifecycleManager {
  private executions: Map<string, NodeExecution> = new Map();
  private listeners: Map<string, Set<NodeLifecycleListener>> = new Map();

  /**
   * Start a node execution
   */
  async start(request: StartNodeRequest): Promise<NodeExecution> {
    const key = this.getExecutionKey(request.runId, request.nodeId);

    // Check if already exists
    const existing = this.executions.get(key);
    if (existing && existing.status === "running") {
      throw new Error(`Node ${request.nodeId} is already running in run ${request.runId}`);
    }

    const attempt: NodeAttempt = {
      attemptId: request.attemptId,
      startedAt: new Date().toISOString(),
      status: "running",
    };

    const execution: NodeExecution = {
      nodeId: request.nodeId,
      runId: request.runId,
      attemptId: request.attemptId,
      status: "running",
      startedAt: new Date().toISOString(),
      input: request.input,
      checkpoints: [],
      attempts: [attempt],
    };

    this.executions.set(key, execution);
    await this.emit("node.started", execution);

    return execution;
  }

  /**
   * Create a checkpoint for a node
   */
  async checkpoint(request: CheckpointNodeRequest): Promise<NodeCheckpoint> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    if (execution.status !== "running" && execution.status !== "checkpoint") {
      throw new Error(`Cannot checkpoint node ${request.nodeId} in status ${execution.status}`);
    }

    const checkpoint: NodeCheckpoint = {
      id: `cp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      nodeId: request.nodeId,
      timestamp: new Date().toISOString(),
      state: request.state,
      stateHash: this.hashState(request.state),
    };

    execution.checkpoints.push(checkpoint);
    execution.status = "checkpoint";

    await this.emit("node.checkpoint", execution);

    return checkpoint;
  }

  /**
   * Put a node in waiting state
   */
  async wait(request: WaitNodeRequest): Promise<void> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    execution.status = "waiting";
    execution.metadata = {
      ...execution.metadata,
      waitReason: request.reason,
      waitMessage: request.message,
      waitTimeout: request.timeoutMs,
      waitStartedAt: new Date().toISOString(),
    };

    await this.emit("node.waiting", execution);
  }

  /**
   * Resume a waiting node
   */
  async resume(request: ResumeNodeRequest): Promise<NodeExecution> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    if (
      execution.status !== "waiting" &&
      execution.status !== "checkpoint" &&
      execution.status !== "failed"
    ) {
      throw new Error(`Cannot resume node ${request.nodeId} in status ${execution.status}`);
    }

    // Create new attempt
    const attempt: NodeAttempt = {
      attemptId: request.attemptId,
      startedAt: new Date().toISOString(),
      status: "running",
    };

    execution.attemptId = request.attemptId;
    execution.status = "running";
    execution.attempts.push(attempt);

    if (request.input !== undefined) {
      execution.input = request.input;
    }

    // Clear wait metadata
    if (execution.metadata) {
      delete execution.metadata.waitReason;
      delete execution.metadata.waitMessage;
      delete execution.metadata.waitTimeout;
      delete execution.metadata.waitStartedAt;
    }

    await this.emit("node.resumed", execution);

    return execution;
  }

  /**
   * Complete a node execution successfully
   */
  async complete(request: CompleteNodeRequest): Promise<NodeExecution> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    if (execution.attemptId !== request.attemptId) {
      throw new Error(
        `Attempt ID mismatch for node ${request.nodeId}: expected ${execution.attemptId}, got ${request.attemptId}`,
      );
    }

    execution.status = "completed";
    execution.output = request.output;
    execution.completedAt = new Date().toISOString();

    // Update current attempt
    const currentAttempt = execution.attempts[execution.attempts.length - 1];
    currentAttempt.status = "completed";
    currentAttempt.completedAt = execution.completedAt;
    currentAttempt.durationMs = request.usage.durationMs;

    await this.emit("node.completed", execution);

    return execution;
  }

  /**
   * Mark a node execution as failed
   */
  async fail(request: FailNodeRequest): Promise<NodeExecution> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    if (execution.attemptId !== request.attemptId) {
      throw new Error(
        `Attempt ID mismatch for node ${request.nodeId}: expected ${execution.attemptId}, got ${request.attemptId}`,
      );
    }

    execution.status = "failed";
    execution.error = request.error;
    execution.completedAt = new Date().toISOString();

    // Update current attempt
    const currentAttempt = execution.attempts[execution.attempts.length - 1];
    currentAttempt.status = "failed";
    currentAttempt.error = request.error;
    currentAttempt.completedAt = execution.completedAt;
    currentAttempt.durationMs = request.usage.durationMs;

    await this.emit("node.failed", execution);

    return execution;
  }

  /**
   * Cancel a node execution
   */
  async cancel(request: CancelNodeRequest): Promise<NodeExecution> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    if (execution.status === "completed" || execution.status === "failed") {
      throw new Error(
        `Cannot cancel node ${request.nodeId} in terminal status ${execution.status}`,
      );
    }

    execution.status = "cancelled";
    execution.completedAt = new Date().toISOString();
    execution.metadata = {
      ...execution.metadata,
      cancelReason: request.reason,
    };

    // Update current attempt if exists
    if (execution.attempts.length > 0) {
      const currentAttempt = execution.attempts[execution.attempts.length - 1];
      if (currentAttempt.status === "running") {
        currentAttempt.status = "cancelled";
        currentAttempt.completedAt = execution.completedAt;
      }
    }

    await this.emit("node.cancelled", execution);

    return execution;
  }

  /**
   * Request replanning for a node
   */
  async replan(request: ReplanRequest): Promise<void> {
    const key = this.getExecutionKey(request.runId, request.nodeId);
    const execution = this.executions.get(key);

    if (!execution) {
      throw new Error(`Node ${request.nodeId} not found in run ${request.runId}`);
    }

    execution.status = "replanning";
    execution.metadata = {
      ...execution.metadata,
      replanReason: request.reason,
      replanRequired: request.newPlanRequired,
      replanRequestedAt: new Date().toISOString(),
    };

    await this.emit("node.replanning", execution);
  }

  /**
   * Get node execution status
   */
  getExecution(runId: string, nodeId: string): NodeExecution | undefined {
    const key = this.getExecutionKey(runId, nodeId);
    return this.executions.get(key);
  }

  /**
   * Get all executions for a run
   */
  getRunExecutions(runId: string): NodeExecution[] {
    return Array.from(this.executions.values()).filter((exec) => exec.runId === runId);
  }

  /**
   * Get execution statistics for a run
   */
  getRunStatistics(runId: string): NodeExecutionStatistics {
    const executions = this.getRunExecutions(runId);

    const stats: NodeExecutionStatistics = {
      total: executions.length,
      pending: 0,
      running: 0,
      checkpoint: 0,
      waiting: 0,
      completed: 0,
      failed: 0,
      cancelled: 0,
      replanning: 0,
      totalAttempts: 0,
      totalCheckpoints: 0,
    };

    for (const exec of executions) {
      stats[exec.status]++;
      stats.totalAttempts += exec.attempts.length;
      stats.totalCheckpoints += exec.checkpoints.length;
    }

    return stats;
  }

  /**
   * Subscribe to lifecycle events
   */
  subscribe(listener: NodeLifecycleListener): () => void {
    const runId = listener.runId || "*";
    if (!this.listeners.has(runId)) {
      this.listeners.set(runId, new Set());
    }
    const listeners = this.listeners.get(runId);
    if (!listeners) throw new Error(`Failed to initialize listeners for run ${runId}`);
    listeners.add(listener);

    // Return unsubscribe function
    return () => {
      this.listeners.get(runId)?.delete(listener);
    };
  }

  /**
   * Clear all executions for a run
   */
  clearRun(runId: string): void {
    const keys = Array.from(this.executions.keys()).filter((key) => key.startsWith(`${runId}:`));
    for (const key of keys) {
      this.executions.delete(key);
    }
  }

  private getExecutionKey(runId: string, nodeId: string): string {
    return `${runId}:${nodeId}`;
  }

  private hashState(state: unknown): string {
    const json = JSON.stringify(state);
    // Simple hash for now - in production would use crypto
    let hash = 0;
    for (let i = 0; i < json.length; i++) {
      const char = json.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash = hash & hash;
    }
    return hash.toString(36);
  }

  private async emit(event: string, execution: NodeExecution): Promise<void> {
    // Emit to run-specific listeners
    const runListeners = this.listeners.get(execution.runId);
    if (runListeners) {
      for (const listener of runListeners) {
        await listener.onEvent?.(event, execution);
      }
    }

    // Emit to global listeners
    const globalListeners = this.listeners.get("*");
    if (globalListeners) {
      for (const listener of globalListeners) {
        await listener.onEvent?.(event, execution);
      }
    }
  }
}

export interface NodeLifecycleListener {
  runId?: string; // If omitted, listens to all runs
  onEvent?(event: string, execution: NodeExecution): Promise<void> | void;
}

export interface NodeExecutionStatistics {
  total: number;
  pending: number;
  running: number;
  checkpoint: number;
  waiting: number;
  completed: number;
  failed: number;
  cancelled: number;
  replanning: number;
  totalAttempts: number;
  totalCheckpoints: number;
}
