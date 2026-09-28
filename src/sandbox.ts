import { Type } from "typebox";
import type { McpPoolTool, ToolScope } from "./tool-pool.js";

export type SandboxCommand = { argv: string[]; cwd?: string; timeoutMs?: number };

export interface SandboxProvider {
  execute(input: SandboxCommand, scope: ToolScope): Promise<unknown>;
}

export function selectSandboxProvider(
  id: string,
  dockerProvider: SandboxProvider,
): SandboxProvider | undefined {
  if (id === "docker") return dockerProvider;
  if (id === "none") return undefined;
  throw new Error(`Unsupported sandbox provider '${id}'`);
}

export function createSandboxTool(provider: SandboxProvider): McpPoolTool {
  return {
    name: "sandbox.execute",
    description: "Run a command in this agent's persistent, network-isolated Docker workspace.",
    schema: Type.Object({
      argv: Type.Array(Type.String({ maxLength: 2000 }), { minItems: 1, maxItems: 64 }),
      cwd: Type.Optional(Type.String({ maxLength: 1000 })),
      timeoutMs: Type.Optional(Type.Integer({ minimum: 1, maximum: 300_000 })),
    }),
    mutates: true,
    timeoutMs: 300_000,
    agents: ["*"],
    authorize: () => true,
    execute(input, scope) {
      return provider.execute(input as SandboxCommand, scope);
    },
  };
}
