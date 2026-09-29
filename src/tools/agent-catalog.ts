import { Type } from "typebox";
import type { AgentPool } from "../registry.js";
import type { McpPoolTool } from "../tool-pool.js";

export function createAgentCatalogTool(pluginRegistry: AgentPool): McpPoolTool {
  return {
    name: "agents.catalog",
    description: "Find registered agents by capability without exposing prompts or credentials.",
    schema: Type.Object({
      capability: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
    }),
    mutates: false,
    agents: ["*"],
    authorize: (scope) => Boolean(scope.agentId),
    async execute(input) {
      const value = input as { capability?: string };
      const agents = value.capability
        ? pluginRegistry.findByCapability(value.capability)
        : pluginRegistry.delegatable();
      return {
        agents: agents.map(({ descriptor }) => ({
          id: descriptor.id,
          version: descriptor.version,
          name: descriptor.name,
          description: descriptor.description,
          capabilities: descriptor.capabilities ?? [],
          inputSchema: descriptor.input,
          outputSchema: descriptor.output,
          modelProfile: descriptor.modelProfile,
          acceptsDelegation: descriptor.acceptsDelegation,
        })),
      };
    },
  };
}
