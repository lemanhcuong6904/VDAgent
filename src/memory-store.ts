import { Type } from "typebox";
import type { McpPoolTool, ToolScope } from "./tool-pool.js";

export interface AgentMemoryProvider {
  remember(input: { key?: string; text: string; tags?: string[] }, scope: ToolScope): Promise<void>;
  search(
    query: string,
    scope: ToolScope,
  ): Promise<Array<{ id: string; key: string | null; text: string; tags: string[] }>>;
  forget(id: string, scope: ToolScope): Promise<boolean>;
}

export function createAgentMemoryTools(store: AgentMemoryProvider): McpPoolTool[] {
  return [
    {
      name: "memory.remember",
      description: "Save or update a durable note in this agent's private PostgreSQL memory.",
      schema: Type.Object({
        key: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
        text: Type.String({ minLength: 1, maxLength: 4000 }),
        tags: Type.Optional(Type.Array(Type.String({ maxLength: 64 }), { maxItems: 12 })),
      }),
      mutates: true,
      alwaysAvailable: true,
      agents: ["*"],
      authorize: () => true,
      async execute(input, scope) {
        await store.remember(input as { key?: string; text: string; tags?: string[] }, scope);
        return { saved: true };
      },
    },
    {
      name: "memory.search",
      description: "Find the most relevant notes in this agent's private durable memory.",
      schema: Type.Object({ query: Type.String({ minLength: 1, maxLength: 500 }) }),
      mutates: false,
      alwaysAvailable: true,
      agents: ["*"],
      authorize: () => true,
      execute(input, scope) {
        return store.search((input as { query: string }).query, scope);
      },
    },
    {
      name: "memory.forget",
      description: "Permanently delete one note from this agent's private memory by ID.",
      schema: Type.Object({ id: Type.String({ minLength: 1, maxLength: 128 }) }),
      mutates: true,
      alwaysAvailable: true,
      agents: ["*"],
      authorize: () => true,
      execute(input, scope) {
        return store.forget((input as { id: string }).id, scope).then((deleted) => ({ deleted }));
      },
    },
  ];
}
