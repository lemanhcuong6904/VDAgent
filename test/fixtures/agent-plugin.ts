import { Type } from "typebox";
import type { AgentPlugin } from "../../src/agent-contract.js";

export const agentPlugin: AgentPlugin = {
  descriptor: {
    apiVersion: "agent-plugin.v1",
    id: "example.summary",
    version: "1.0.0",
    name: "Example summary",
    description: "Summarize an input using the shared Pi runtime.",
    input: Type.Object({ text: Type.String({ minLength: 1, maxLength: 4000 }) }),
    output: Type.String(),
    tools: [],
  },
  run(input, context) {
    const value = input as { text: string };
    return context.runtime.prompt({
      agentId: "example.summary",
      system: "Summarize the supplied text accurately and concisely.",
      prompt: value.text,
      tools: [],
      scope: {
        userId: context.userId,
        spaceId: context.spaceId,
        sessionId: context.sessionId,
        signal: context.signal,
      },
      pool: context.pool,
    });
  },
};
