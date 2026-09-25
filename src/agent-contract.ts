import type { TSchema } from "typebox";
import type { PiRuntime } from "./pi-runtime.js";
import type { McpPoolTool, McpToolPool } from "./tool-pool.js";

export interface AgentContext {
  runId: string;
  sessionId: string;
  userId: string;
  spaceId: string;
  taskId?: string;
  depth?: number;
  signal: AbortSignal;
  tools: readonly McpPoolTool[];
  runtime: PiRuntime;
  pool: McpToolPool;
  publish?: (userId: string, event: string, data: Record<string, unknown>) => void;
}

export interface AgentPlugin {
  descriptor: {
    apiVersion?: "agent-plugin.v1";
    id: string;
    version: string;
    name: string;
    description: string;
    capabilities?: readonly string[];
    input: TSchema;
    output?: TSchema;
    guardrails?: readonly string[];
    tools: readonly string[];
  };
  run(input: unknown, context: AgentContext): Promise<unknown>;
}
