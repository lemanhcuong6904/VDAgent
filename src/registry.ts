import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { AgentPlugin } from "./agent-contract.js";

export class AgentPool {
  private readonly plugins = new Map<string, AgentPlugin>();

  register(plugin: AgentPlugin): void {
    const { id, version, input, tools } = plugin.descriptor;
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(id)) throw new Error(`Invalid agent id '${id}'`);
    if (!version.trim()) throw new Error(`Agent '${id}' must have a version`);
    if (this.plugins.has(id)) throw new Error(`Agent '${id}' is already registered`);
    this.plugins.set(id, {
      ...plugin,
      descriptor: {
        ...plugin.descriptor,
        apiVersion: plugin.descriptor.apiVersion ?? "agent-plugin.v1",
        capabilities: [...(plugin.descriptor.capabilities ?? [])],
        guardrails: [...(plugin.descriptor.guardrails ?? [])],
        input,
        tools: [...tools],
      },
    });
  }

  get(id: string): AgentPlugin | undefined {
    return this.plugins.get(id);
  }

  list() {
    return [...this.plugins.values()].map(({ descriptor }) => ({
      id: descriptor.id,
      version: descriptor.version,
      name: descriptor.name,
      description: descriptor.description,
      apiVersion: descriptor.apiVersion,
      capabilities: descriptor.capabilities,
      inputSchema: descriptor.input,
      outputSchema: descriptor.output,
      guardrails: descriptor.guardrails,
      tools: descriptor.tools,
    }));
  }
}

export async function loadAgentPool(specifiers: readonly string[]): Promise<AgentPool> {
  const registry = new AgentPool();
  for (const specifier of specifiers) {
    const url = specifier.startsWith("file:") ? specifier : pathToFileURL(resolve(specifier)).href;
    const module = await import(url);
    const plugins: unknown[] = Array.isArray(module.plugins)
      ? module.plugins
      : module.agentPlugin
        ? [module.agentPlugin]
        : [];
    if (plugins.length === 0) throw new Error(`Agent module '${specifier}' exports no plugins`);
    for (const plugin of plugins) registry.register(plugin as AgentPlugin);
  }
  return registry;
}
