/**
 * Child Run Management
 * Typed child runs with depth/fan-out/budget/deadline/trace tracking
 */

import type { AgentScope } from "../contracts/index.js";

/**
 * Child run limits and constraints
 */
export interface ChildRunLimits {
  maxDepth: number;
  maxFanOut: number;
  maxBudgetUsd?: number;
  deadlineMs?: number;
}

/**
 * Child run trace context
 */
export interface TraceContext {
  traceId: string;
  parentSpanId?: string;
  spanId: string;
  depth: number;
  rootRunId: string;
  parentRunId: string;
  correlationId?: string;
  causationId?: string;
}

/**
 * Budget tracking
 */
export interface BudgetTracker {
  allocatedUsd: number;
  consumedUsd: number;
  remainingUsd: number;
  childAllocations: Map<string, number>;
}

/**
 * Deadline tracking
 */
export interface DeadlineTracker {
  deadlineAt: string;
  startedAt: string;
  remainingMs: number;
  expired: boolean;
}

/**
 * Child run specification
 */
export interface ChildRunSpec<TInput = unknown> {
  runId: string;
  workflowId: string;
  /** Host-bound scope; absent when the caller bound none (identity is never fabricated). */
  scope?: AgentScope;
  input: TInput;
  trace: TraceContext;
  limits: ChildRunLimits;
  budget?: BudgetTracker;
  deadline?: DeadlineTracker;
  metadata?: Record<string, unknown>;
}

/**
 * Child run result
 */
export interface ChildRunResult<TOutput = unknown> {
  runId: string;
  status: "completed" | "failed" | "timeout" | "budget_exceeded" | "depth_exceeded";
  output?: TOutput;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
  usage: {
    durationMs: number;
    costUsd?: number;
    tokensUsed?: number;
  };
  trace: TraceContext;
  completedAt: string;
}

/**
 * Fan-out state tracking
 */
export interface FanOutState {
  parentRunId: string;
  childRunIds: string[];
  maxFanOut: number;
  completed: number;
  failed: number;
  active: number;
}

/**
 * Child run manager
 */
export class ChildRunManager {
  private childSpecs: Map<string, ChildRunSpec> = new Map();
  private childResults: Map<string, ChildRunResult> = new Map();
  private fanOutState: Map<string, FanOutState> = new Map();
  private depthTracking: Map<string, number> = new Map();

  /**
   * Create a child run spec
   */
  createChildRun<TInput = unknown>(
    parentRunId: string,
    parentTrace: TraceContext,
    parentLimits: ChildRunLimits,
    input: TInput,
    options?: {
      workflowId?: string;
      scope?: AgentScope;
      budgetUsd?: number;
      deadlineMs?: number;
      metadata?: Record<string, unknown>;
    },
  ): ChildRunSpec<TInput> | { error: string } {
    // Check depth limit
    const newDepth = parentTrace.depth + 1;
    if (newDepth > parentLimits.maxDepth) {
      return { error: `Depth limit exceeded: ${newDepth} > ${parentLimits.maxDepth}` };
    }

    // Check fan-out limit
    const fanOut = this.fanOutState.get(parentRunId) || {
      parentRunId,
      childRunIds: [],
      maxFanOut: parentLimits.maxFanOut,
      completed: 0,
      failed: 0,
      active: 0,
    };

    if (fanOut.childRunIds.length >= parentLimits.maxFanOut) {
      return {
        error: `Fan-out limit exceeded: ${fanOut.childRunIds.length} >= ${parentLimits.maxFanOut}`,
      };
    }

    // Generate child run ID and span ID
    const runId = `run-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    const spanId = `span-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

    // Create trace context
    const trace: TraceContext = {
      traceId: parentTrace.traceId,
      parentSpanId: parentTrace.spanId,
      spanId,
      depth: newDepth,
      rootRunId: parentTrace.rootRunId,
      parentRunId,
      correlationId: parentTrace.correlationId,
      causationId: runId,
    };

    // Create budget tracker if budget allocated
    let budget: BudgetTracker | undefined;
    if (options?.budgetUsd !== undefined && options.budgetUsd > 0) {
      budget = {
        allocatedUsd: options.budgetUsd,
        consumedUsd: 0,
        remainingUsd: options.budgetUsd,
        childAllocations: new Map(),
      };
    }

    // Create deadline tracker if deadline specified
    let deadline: DeadlineTracker | undefined;
    if (options?.deadlineMs !== undefined && options.deadlineMs > 0) {
      const now = new Date();
      const deadlineAt = new Date(now.getTime() + options.deadlineMs);
      deadline = {
        deadlineAt: deadlineAt.toISOString(),
        startedAt: now.toISOString(),
        remainingMs: options.deadlineMs,
        expired: false,
      };
    }

    // Create child run spec
    const spec: ChildRunSpec<TInput> = {
      runId,
      workflowId: options?.workflowId || `workflow-${runId}`,
      scope: options?.scope,
      input,
      trace,
      limits: parentLimits,
      budget,
      deadline,
      metadata: options?.metadata,
    };

    // Store spec and update tracking
    this.childSpecs.set(runId, spec);
    this.depthTracking.set(runId, newDepth);

    // Update fan-out state
    fanOut.childRunIds.push(runId);
    fanOut.active++;
    this.fanOutState.set(parentRunId, fanOut);

    return spec;
  }

  /**
   * Record child run result
   */
  recordResult<TOutput = unknown>(runId: string, result: ChildRunResult<TOutput>): void {
    const spec = this.childSpecs.get(runId);
    if (!spec) {
      throw new Error(`Child run ${runId} not found`);
    }

    // Update budget if tracked
    if (spec.budget && result.usage.costUsd !== undefined) {
      spec.budget.consumedUsd += result.usage.costUsd;
      spec.budget.remainingUsd = Math.max(0, spec.budget.allocatedUsd - spec.budget.consumedUsd);
    }

    // Update deadline if tracked
    if (spec.deadline) {
      const now = new Date();
      const deadlineAt = new Date(spec.deadline.deadlineAt);
      spec.deadline.remainingMs = Math.max(0, deadlineAt.getTime() - now.getTime());
      spec.deadline.expired = now >= deadlineAt;
    }

    // Store result
    this.childResults.set(runId, result);

    // Update fan-out state
    const parentRunId = spec.trace.parentRunId;
    const fanOut = this.fanOutState.get(parentRunId);
    if (fanOut) {
      fanOut.active--;
      if (result.status === "completed") {
        fanOut.completed++;
      } else {
        fanOut.failed++;
      }
      this.fanOutState.set(parentRunId, fanOut);
    }
  }

  /**
   * Check if child run can proceed
   */
  canProceed(runId: string): { ok: boolean; reason?: string } {
    const spec = this.childSpecs.get(runId);
    if (!spec) {
      return { ok: false, reason: "Run not found" };
    }

    // Check deadline
    if (spec.deadline) {
      const now = new Date();
      const deadlineAt = new Date(spec.deadline.deadlineAt);
      if (now >= deadlineAt) {
        return { ok: false, reason: "Deadline exceeded" };
      }
    }

    // Check budget
    if (spec.budget && spec.budget.remainingUsd <= 0) {
      return { ok: false, reason: "Budget exhausted" };
    }

    return { ok: true };
  }

  /**
   * Get child run spec
   */
  getSpec(runId: string): ChildRunSpec | undefined {
    return this.childSpecs.get(runId);
  }

  /**
   * Get child run result
   */
  getResult(runId: string): ChildRunResult | undefined {
    return this.childResults.get(runId);
  }

  /**
   * Get fan-out state for a parent run
   */
  getFanOutState(parentRunId: string): FanOutState | undefined {
    return this.fanOutState.get(parentRunId);
  }

  /**
   * Get all child runs for a parent
   */
  getChildRuns(parentRunId: string): ChildRunSpec[] {
    return Array.from(this.childSpecs.values()).filter(
      (spec) => spec.trace.parentRunId === parentRunId,
    );
  }

  /**
   * Get all results for a parent's children
   */
  getChildResults(parentRunId: string): ChildRunResult[] {
    const childRunIds = this.getChildRuns(parentRunId).map((spec) => spec.runId);
    return childRunIds
      .map((runId) => this.childResults.get(runId))
      .filter((result): result is ChildRunResult => result !== undefined);
  }

  /**
   * Get depth of a run
   */
  getDepth(runId: string): number | undefined {
    return this.depthTracking.get(runId);
  }

  /**
   * Get trace path from root to run
   */
  getTracePath(runId: string): string[] {
    const path: string[] = [];
    let currentRunId: string | undefined = runId;

    while (currentRunId) {
      path.unshift(currentRunId);
      const spec = this.childSpecs.get(currentRunId);
      if (!spec || spec.trace.parentRunId === spec.trace.rootRunId) {
        break;
      }
      currentRunId = spec.trace.parentRunId;
    }

    return path;
  }

  /**
   * Get aggregated statistics
   */
  getStatistics(): {
    totalRuns: number;
    byDepth: Map<number, number>;
    totalCostUsd: number;
    totalDurationMs: number;
    byStatus: Record<string, number>;
  } {
    const byDepth = new Map<number, number>();
    let totalCostUsd = 0;
    let totalDurationMs = 0;
    const byStatus: Record<string, number> = {
      completed: 0,
      failed: 0,
      timeout: 0,
      budget_exceeded: 0,
      depth_exceeded: 0,
    };

    for (const [runId, result] of this.childResults) {
      const depth = this.depthTracking.get(runId) || 0;
      byDepth.set(depth, (byDepth.get(depth) || 0) + 1);

      totalCostUsd += result.usage.costUsd || 0;
      totalDurationMs += result.usage.durationMs;
      byStatus[result.status]++;
    }

    return {
      totalRuns: this.childResults.size,
      byDepth,
      totalCostUsd,
      totalDurationMs,
      byStatus,
    };
  }

  /**
   * Clean up completed runs
   */
  cleanup(runId: string): void {
    const spec = this.childSpecs.get(runId);
    if (spec) {
      // Clean up all descendants first
      const children = this.getChildRuns(runId);
      for (const child of children) {
        this.cleanup(child.runId);
      }

      // Clean up this run
      this.childSpecs.delete(runId);
      this.childResults.delete(runId);
      this.depthTracking.delete(runId);
      this.fanOutState.delete(runId);
    }
  }
}
