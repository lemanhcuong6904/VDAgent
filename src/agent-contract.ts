import type { TSchema } from "typebox";
import type { TraceContext } from "./observability.js";
import type { PlannerCatalog } from "./planner.js";
import type { McpPoolTool, McpToolPool } from "./tool-pool.js";

export interface AgentRuntime {
  prompt(input: {
    agentId: string;
    system: string;
    prompt: string;
    tools: readonly string[];
    modelProfile?: string;
    scope: {
      userId: string;
      spaceId: string;
      sessionId?: string;
      runId?: string;
      taskId?: string;
      depth?: number;
      trace?: TraceContext;
      signal: AbortSignal;
      publish?: (userId: string, event: string, data: Record<string, unknown>) => void;
    };
    pool: McpToolPool;
  }): Promise<string>;
}

export interface AgentContext {
  runId: string;
  sessionId: string;
  userId: string;
  spaceId: string;
  taskId?: string;
  parentRunId?: string;
  depth?: number;
  modelProfile?: string;
  catalog?: PlannerCatalog;
  trace?: TraceContext;
  signal: AbortSignal;
  tools: readonly McpPoolTool[];
  runtime: AgentRuntime;
  pool: McpToolPool;
  publish?: (userId: string, event: string, data: Record<string, unknown>) => void;
}

export interface AgentPlugin {
  descriptor: {
    apiVersion?: "agent-plugin.v1" | "agent-plugin.v2";
    id: string;
    version: string;
    name: string;
    description: string;
    capabilities?: readonly string[];
    requiredCapabilities?: readonly string[];
    modelProfile?: string;
    acceptsDelegation?: boolean;
    limits?: {
      maxDepth?: number;
      maxParallelChildren?: number;
      maxToolCalls?: number;
      maxDurationMs?: number;
      maxTokens?: number;
    };
    input: TSchema;
    output?: TSchema;
    guardrails?: readonly string[];
    tools: readonly string[];
  };
  run(input: unknown, context: AgentContext): Promise<unknown>;
}
