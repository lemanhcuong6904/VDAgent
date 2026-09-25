import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { TSchema } from "typebox";
import { Value } from "typebox/value";

export interface ToolScope {
  userId: string;
  spaceId: string;
  agentId?: string;
  sessionId?: string;
  runId?: string;
  taskId?: string;
  depth?: number;
  toolCallId?: string;
  publish?: (userId: string, event: string, data: Record<string, unknown>) => void;
  signal: AbortSignal;
}

export interface McpPoolTool {
  name: string;
  description: string;
  schema: TSchema;
  mutates: boolean;
  timeoutMs?: number;
  agents: readonly string[];
  alwaysAvailable?: boolean;
  authorize(scope: ToolScope): boolean | Promise<boolean>;
  execute(input: unknown, scope: ToolScope): Promise<unknown>;
}

export class McpToolPool {
  private readonly tools = new Map<string, McpPoolTool>();

  register(tool: McpPoolTool): void {
    if (!/^[a-zA-Z0-9_.-]{1,128}$/.test(tool.name)) throw new Error("Invalid tool name");
    if (this.tools.has(tool.name)) throw new Error(`Tool '${tool.name}' is already registered`);
    if (tool.agents.length === 0) throw new Error(`Tool '${tool.name}' must name allowed agents`);
    const timeoutMs = tool.timeoutMs ?? 30_000;
    if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 300_000) {
      throw new Error(`Tool '${tool.name}' timeout must be from 1 to 300000 milliseconds`);
    }
    this.tools.set(tool.name, { ...tool, timeoutMs });
  }

  forAgent(agentId: string) {
    return [...this.tools.values()].filter(
      (tool) => tool.agents.includes(agentId) || tool.agents.includes("*"),
    );
  }

  forNames(names: readonly string[]) {
    const requested = new Set(names);
    return [...this.tools.values()].filter((tool) => requested.has(tool.name));
  }

  async call(name: string, input: unknown, scope: ToolScope, agentId: string): Promise<unknown> {
    const tool = this.tools.get(name);
    if (
      !tool ||
      (!tool.agents.includes(agentId) && !tool.agents.includes("*")) ||
      !(await tool.authorize({ ...scope, agentId }))
    ) {
      throw new Error(`Tool '${name}' is not authorized for agent '${agentId}'`);
    }
    if (!Value.Check(tool.schema, input)) throw new Error(`Invalid input for tool '${name}'`);
    scope.signal.throwIfAborted();
    const timeoutController = new AbortController();
    const timeout = setTimeout(
      () => timeoutController.abort(new Error("Tool timed out")),
      tool.timeoutMs,
    );
    const signal = AbortSignal.any([scope.signal, timeoutController.signal]);
    let onAbort: () => void = () => undefined;
    let result: unknown;
    try {
      result = await Promise.race([
        tool.execute(input, { ...scope, agentId, signal }),
        new Promise<never>((_resolve, reject) => {
          onAbort = () => reject(signal.reason);
          signal.addEventListener("abort", onAbort, { once: true });
          if (signal.aborted) onAbort();
        }),
      ]);
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", onAbort);
    }
    const encoded = JSON.stringify(result);
    if (encoded === undefined || Buffer.byteLength(encoded) > 1_000_000) {
      throw new Error("Tool result must be JSON and at most 1 MB");
    }
    return result;
  }
}

export async function loadToolPool(
  specifiers: readonly string[],
  services: { database?: unknown } = {},
): Promise<McpToolPool> {
  const pool = new McpToolPool();
  for (const specifier of specifiers) {
    const url = specifier.startsWith("file:") ? specifier : pathToFileURL(resolve(specifier)).href;
    const module = await import(url);
    const tools =
      typeof module.createTools === "function"
        ? ((await module.createTools(services)) as McpPoolTool[])
        : Array.isArray(module.tools)
          ? (module.tools as McpPoolTool[])
          : undefined;
    if (!tools) throw new Error(`Tool module '${specifier}' exports no tools`);
    for (const tool of tools) pool.register(tool);
  }
  return pool;
}
