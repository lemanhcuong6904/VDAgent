import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import type { AgentPlugin } from "../src/agent-contract.js";
import { AgentPool } from "../src/registry.js";
import { McpToolPool } from "../src/tool-pool.js";
import { createAgentCommunicationTools } from "../src/tools/agent-communication.js";

function plugin(id: string, capabilities: string[] = []): AgentPlugin {
  return {
    descriptor: {
      id,
      version: "1.0.0",
      name: id,
      description: id,
      capabilities,
      acceptsDelegation: true,
      input: Type.Object({ prompt: Type.String() }),
      tools: ["agents.send", "agents.wait", "agents.result"],
    },
    async run() {
      return "ok";
    },
  };
}

describe("agent communication ports", () => {
  it("requires a scoped invocation before exposing send/wait/result", async () => {
    const registry = new AgentPool();
    registry.register(plugin("sender"));
    registry.register(plugin("receiver"));
    const pool = new McpToolPool();
    pool.registerAgentManifest("sender", ["agents.send", "agents.wait", "agents.result"]);
    pool.registerAgentManifest("receiver", ["agents.send", "agents.wait", "agents.result"]);
    for (const tool of createAgentCommunicationTools({
      database: {} as never,
      runLedger: {} as never,
      pluginRegistry: registry,
    })) {
      pool.register(tool);
    }

    expect(pool.forAgent("sender").map(({ name }) => name)).toEqual([
      "agents.send",
      "agents.wait",
      "agents.result",
    ]);
    await expect(
      pool.call(
        "agents.send",
        { agent: "receiver", message: "hello" },
        { userId: "u1", spaceId: "s1", signal: new AbortController().signal },
        "sender",
      ),
    ).rejects.toThrow("not authorized");
  });

  it("keeps an explicit sender-to-target edge policy", async () => {
    const registry = new AgentPool();
    registry.register(plugin("sender"));
    registry.register(plugin("receiver"));
    registry.register(plugin("blocked"));
    const pool = new McpToolPool();
    pool.registerAgentManifest("sender", ["agents.send"]);
    pool.register(
      createAgentCommunicationTools({
        database: {} as never,
        runLedger: {} as never,
        pluginRegistry: registry,
        allowedEdges: new Map([["sender", new Set(["receiver"])]]),
      })[0],
    );
    const scope = {
      userId: "u1",
      spaceId: "s1",
      taskId: "task-1",
      runId: "inv-1",
      agentId: "sender",
      signal: new AbortController().signal,
    };
    await expect(
      pool.call("agents.send", { agent: "blocked", message: "hello" }, scope, "sender"),
    ).rejects.toThrow("not allowed");
  });
});
