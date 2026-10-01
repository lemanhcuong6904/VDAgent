/**
 * Collaboration Port
 * Enables agents to discover, invoke, and wait for results from other agents
 */

import type { AgentScope } from "../contracts/index.js";

/**
 * Agent capability descriptor
 */
export interface AgentCapability {
  agentId: string;
  name: string;
  description: string;
  capabilities: string[];
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  costEstimate?: {
    minUsd: number;
    maxUsd: number;
  };
  durationEstimate?: {
    minMs: number;
    maxMs: number;
  };
  metadata?: Record<string, unknown>;
}

/**
 * Delegation request
 */
export interface DelegationRequest {
  requestId: string;
  callerRunId: string;
  targetAgentId: string;
  scope: AgentScope;
  input: unknown;
  timeout?: number;
  priority?: "low" | "normal" | "high";
  traceId?: string;
  parentSpanId?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Delegation response
 */
export interface DelegationResponse {
  requestId: string;
  childRunId: string;
  status: "accepted" | "rejected" | "queued";
  reason?: string;
  estimatedCompletionMs?: number;
}

/**
 * Delegation result
 */
export interface DelegationResult {
  requestId: string;
  childRunId: string;
  status: "completed" | "failed" | "timeout" | "cancelled";
  output?: unknown;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
  usage?: {
    durationMs: number;
    costUsd?: number;
    tokensUsed?: number;
  };
  completedAt: string;
}

/**
 * Wait handle for async delegation
 */
export interface WaitHandle {
  requestId: string;
  childRunId: string;
  poll(): Promise<DelegationResult | null>;
  wait(timeoutMs?: number): Promise<DelegationResult>;
  cancel(): Promise<boolean>;
}

/**
 * Discovery filter
 */
export interface DiscoveryFilter {
  capabilities?: string[];
  namePattern?: string;
  maxCostUsd?: number;
  maxDurationMs?: number;
  scope?: AgentScope;
}

/**
 * Port for agent collaboration and delegation
 */
export interface CollaborationPort {
  /**
   * Discover available agents
   */
  discover(filter?: DiscoveryFilter): Promise<AgentCapability[]>;

  /**
   * Invoke an agent and wait for completion
   */
  invoke(request: DelegationRequest): Promise<DelegationResult>;

  /**
   * Invoke an agent asynchronously
   */
  invokeAsync(request: DelegationRequest): Promise<WaitHandle>;

  /**
   * Wait for a delegation to complete
   */
  wait(requestId: string, timeoutMs?: number): Promise<DelegationResult>;

  /**
   * Get delegation status
   */
  getStatus(requestId: string): Promise<DelegationResult | null>;

  /**
   * Cancel a delegation
   */
  cancel(requestId: string): Promise<boolean>;
}

/**
 * In-memory implementation of CollaborationPort
 */
export class InMemoryCollaborationPort implements CollaborationPort {
  private agents: Map<string, AgentCapability> = new Map();
  private delegations: Map<string, DelegationResult> = new Map();
  private handlers: Map<string, AgentHandler> = new Map();
  private cancelled: Set<string> = new Set();
  private inFlight: Set<string> = new Set();

  /**
   * Register an agent
   */
  registerAgent(capability: AgentCapability, handler: AgentHandler): void {
    this.agents.set(capability.agentId, capability);
    this.handlers.set(capability.agentId, handler);
  }

  /**
   * Unregister an agent
   */
  unregisterAgent(agentId: string): void {
    this.agents.delete(agentId);
    this.handlers.delete(agentId);
  }

  async discover(filter?: DiscoveryFilter): Promise<AgentCapability[]> {
    let agents = Array.from(this.agents.values());

    if (filter) {
      const capabilities = filter.capabilities;
      if (capabilities && capabilities.length > 0) {
        agents = agents.filter((agent) =>
          capabilities.some((cap) => agent.capabilities.includes(cap)),
        );
      }

      if (filter.namePattern) {
        const pattern = new RegExp(filter.namePattern, "i");
        agents = agents.filter((agent) => pattern.test(agent.name));
      }

      const maxCostUsd = filter.maxCostUsd;
      if (maxCostUsd !== undefined) {
        agents = agents.filter(
          (agent) => !agent.costEstimate || agent.costEstimate.minUsd < maxCostUsd,
        );
      }

      const maxDurationMs = filter.maxDurationMs;
      if (maxDurationMs !== undefined) {
        agents = agents.filter(
          (agent) => !agent.durationEstimate || agent.durationEstimate.minMs <= maxDurationMs,
        );
      }

      // Scope filtering would check tenant/actor permissions
      // For now, just return filtered agents
    }

    return agents;
  }

  async invoke(request: DelegationRequest): Promise<DelegationResult> {
    const handler = this.handlers.get(request.targetAgentId);
    if (!handler) {
      const result: DelegationResult = {
        requestId: request.requestId,
        childRunId: "",
        status: "failed",
        error: {
          code: "agent_not_found",
          message: `Agent ${request.targetAgentId} not found`,
          retryable: false,
        },
        completedAt: new Date().toISOString(),
      };
      this.delegations.set(request.requestId, result);
      return result;
    }

    try {
      const startTime = Date.now();
      const output = await this.executeWithTimeout(
        () => handler.execute(request.input, request.scope),
        request.timeout || 60000,
      );
      const durationMs = Math.max(1, Date.now() - startTime);

      const result: DelegationResult = {
        requestId: request.requestId,
        childRunId: `child-${request.requestId}`,
        status: "completed",
        output,
        usage: {
          durationMs,
        },
        completedAt: new Date().toISOString(),
      };

      this.delegations.set(request.requestId, result);
      return result;
    } catch (error) {
      const result: DelegationResult = {
        requestId: request.requestId,
        childRunId: `child-${request.requestId}`,
        status: "failed",
        error: {
          code: "execution_error",
          message: error instanceof Error ? error.message : "Unknown error",
          retryable: true,
        },
        completedAt: new Date().toISOString(),
      };

      this.delegations.set(request.requestId, result);
      return result;
    }
  }

  async invokeAsync(request: DelegationRequest): Promise<WaitHandle> {
    const handler = this.handlers.get(request.targetAgentId);
    if (!handler) {
      const result: DelegationResult = {
        requestId: request.requestId,
        childRunId: "",
        status: "failed",
        error: {
          code: "agent_not_found",
          message: `Agent ${request.targetAgentId} not found`,
          retryable: false,
        },
        completedAt: new Date().toISOString(),
      };
      this.delegations.set(request.requestId, result);

      return this.createWaitHandle(request.requestId, "");
    }

    const childRunId = `child-${request.requestId}`;

    // Mark as in-flight
    this.inFlight.add(request.requestId);

    // Execute asynchronously
    (async () => {
      try {
        const startTime = Date.now();
        const output = await this.executeWithTimeout(
          () => handler.execute(request.input, request.scope),
          request.timeout || 60000,
        );
        const durationMs = Date.now() - startTime;

        // Check if cancelled while executing
        if (this.cancelled.has(request.requestId)) {
          return; // Don't overwrite cancellation
        }

        const result: DelegationResult = {
          requestId: request.requestId,
          childRunId,
          status: "completed",
          output,
          usage: {
            durationMs,
          },
          completedAt: new Date().toISOString(),
        };

        this.delegations.set(request.requestId, result);
      } catch (error) {
        // Check if cancelled while executing
        if (this.cancelled.has(request.requestId)) {
          return; // Don't overwrite cancellation
        }

        const result: DelegationResult = {
          requestId: request.requestId,
          childRunId,
          status: "failed",
          error: {
            code: "execution_error",
            message: error instanceof Error ? error.message : "Unknown error",
            retryable: true,
          },
          completedAt: new Date().toISOString(),
        };

        this.delegations.set(request.requestId, result);
      } finally {
        this.inFlight.delete(request.requestId);
      }
    })();

    return this.createWaitHandle(request.requestId, childRunId);
  }

  async wait(requestId: string, timeoutMs?: number): Promise<DelegationResult> {
    const startTime = Date.now();
    const timeout = timeoutMs || 60000;

    while (Date.now() - startTime < timeout) {
      const result = this.delegations.get(requestId);
      if (result) {
        return result;
      }

      await new Promise((resolve) => setTimeout(resolve, 100));
    }

    const timeoutResult: DelegationResult = {
      requestId,
      childRunId: "",
      status: "timeout",
      error: {
        code: "wait_timeout",
        message: `Wait timeout after ${timeout}ms`,
        retryable: true,
      },
      completedAt: new Date().toISOString(),
    };

    this.delegations.set(requestId, timeoutResult);
    return timeoutResult;
  }

  async getStatus(requestId: string): Promise<DelegationResult | null> {
    return this.delegations.get(requestId) || null;
  }

  async cancel(requestId: string): Promise<boolean> {
    const result = this.delegations.get(requestId);
    const isInFlight = this.inFlight.has(requestId);

    // Can only cancel if delegation exists or is in-flight
    if (!result && !isInFlight) {
      return false; // Never heard of this request
    }

    if (result) {
      // Already completed/failed - can't cancel
      if (result.status === "completed" || result.status === "failed") {
        return false;
      }
      // Already cancelled
      if (result.status === "cancelled") {
        return false;
      }
    }

    // Mark as cancelled (even if execution in progress)
    this.cancelled.add(requestId);

    const cancelledResult: DelegationResult = {
      requestId,
      childRunId: result?.childRunId || `child-${requestId}`,
      status: "cancelled",
      error: {
        code: "cancelled",
        message: "Delegation cancelled by caller",
        retryable: false,
      },
      completedAt: new Date().toISOString(),
    };

    this.delegations.set(requestId, cancelledResult);
    return true;
  }

  private createWaitHandle(requestId: string, childRunId: string): WaitHandle {
    return {
      requestId,
      childRunId,
      poll: async () => {
        return this.delegations.get(requestId) || null;
      },
      wait: async (timeoutMs?: number) => {
        return this.wait(requestId, timeoutMs);
      },
      cancel: async () => {
        return this.cancel(requestId);
      },
    };
  }

  private async executeWithTimeout<T>(fn: () => Promise<T>, timeoutMs: number): Promise<T> {
    return Promise.race([
      fn(),
      new Promise<T>((_, reject) =>
        setTimeout(() => reject(new Error(`Execution timeout after ${timeoutMs}ms`)), timeoutMs),
      ),
    ]);
  }
}

/**
 * Agent handler interface
 */
export interface AgentHandler {
  execute(input: unknown, scope: AgentScope): Promise<unknown>;
}
