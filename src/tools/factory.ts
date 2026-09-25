import type { TSchema } from "typebox";
import type { McpPoolTool, ToolScope } from "../tool-pool.js";

export interface SimpleToolDefinition {
  name: string;
  description: string;
  schema: TSchema;
  agents: readonly string[];
  mutates?: boolean;
  timeoutMs?: number;
  alwaysAvailable?: boolean;
  authorize?: (scope: ToolScope) => boolean | Promise<boolean>;
  execute(input: unknown, scope: ToolScope): Promise<unknown>;
}

/** Small MCP pool tool factory; pool validation and policy remain mandatory. */
export function defineTool(definition: SimpleToolDefinition): McpPoolTool {
  return {
    ...definition,
    mutates: definition.mutates ?? false,
    authorize: definition.authorize ?? (() => true),
  };
}
