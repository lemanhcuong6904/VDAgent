import type { TSchema } from "typebox";
import type { AgentContext, AgentPlugin } from "../agent-contract.js";

export interface SimpleAgentDefinition {
  id: string;
  version: string;
  name: string;
  description: string;
  systemPrompt: string;
  inputSchema: TSchema;
  outputSchema?: TSchema;
  capabilities?: readonly string[];
  guardrails?: readonly string[];
  tools?: readonly string[];
  prompt?: (input: unknown) => string;
  run?: (input: unknown, context: AgentContext) => Promise<unknown>;
}

/** Minimal Pi-backed agent definition for independent teams. */
export function defineAgent(definition: SimpleAgentDefinition): AgentPlugin {
  const tools = [...(definition.tools ?? [])];
  return {
    descriptor: {
      id: definition.id,
      version: definition.version,
      name: definition.name,
      description: definition.description,
      apiVersion: "agent-plugin.v1",
      capabilities: [...(definition.capabilities ?? ["pi", "durable-memory", "docker-sandbox"])],
      input: definition.inputSchema,
      output: definition.outputSchema,
      guardrails: [...(definition.guardrails ?? [])],
      tools,
    },
    async run(input, context) {
      if (definition.run) return definition.run(input, context);
      return context.runtime.prompt({
        agentId: definition.id,
        system: definition.systemPrompt,
        prompt: definition.prompt ? definition.prompt(input) : JSON.stringify(input),
        tools: context.tools.map(({ name }) => name),
        scope: {
          userId: context.userId,
          spaceId: context.spaceId,
          sessionId: context.sessionId,
          runId: context.runId,
          taskId: context.taskId,
          depth: context.depth,
          signal: context.signal,
          publish: context.publish,
        },
        pool: context.pool,
      });
    },
  };
}
