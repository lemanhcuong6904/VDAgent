import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import type { AgentPlugin } from "../src/agent-contract.js";
import { AgentPool, validateAgentPlugin } from "../src/registry.js";
import { McpToolPool } from "../src/tool-pool.js";
import { createAgentDelegationTool } from "../src/tools/agent-delegation.js";

function agent(id: string, tools: string[], acceptsDelegation: boolean): AgentPlugin {
  return {
    descriptor: {
      id,
      version: "1.0.0",
      name: id,
      description: `${id} agent`,
      acceptsDelegation,
      input: Type.Object({ prompt: Type.String() }),
      tools,
    },
    run: async () => "ok",
  };
}

function setup() {
  const pluginRegistry = new AgentPool();
  // The delegator id is deliberately not "orchestrator": authority comes from the manifest grant.
  pluginRegistry.register(agent("planner", ["agents.delegate"], false));
  pluginRegistry.register(agent("data", [], true));
  const pool = new McpToolPool();
  pool.register(
    createAgentDelegationTool({
      database: {} as never,
      pluginRegistry,
      pool,
      runtime: {} as never,
    }),
  );
  for (const { id, tools } of pluginRegistry.list()) pool.registerAgentManifest(id, tools);
  return { pluginRegistry, pool };
}

describe("delegation guardrails", () => {
  it("authorizes by manifest grant, not by agent id", async () => {
    const { pool } = setup();
    const scope = { userId: "user", spaceId: "space", signal: new AbortController().signal };

    expect(pool.forAgent("not-registered")).toEqual([]);
    expect(pool.forAgent("data")).toEqual([]);
    expect(pool.forAgent("planner").map(({ name }) => name)).toEqual(["agents.delegate"]);
    await expect(
      pool.call("agents.delegate", { agent: "data", message: "list tables" }, scope, "planner"),
    ).rejects.toThrow("only available to a running root task of a delegator");
    await expect(
      pool.call("agents.delegate", { agent: "data", message: "list tables" }, scope, "data"),
    ).rejects.toThrow("not authorized");
    await expect(
      pool.call("agents.delegate", { agent: "data", message: "x" }, scope, "orchestrator"),
    ).rejects.toThrow("not authorized");
  });

  it("requires a running root task before it starts a child invocation", async () => {
    const { pool } = setup();
    const scope = {
      userId: "user",
      spaceId: "space",
      agentId: "planner",
      depth: 0,
      signal: new AbortController().signal,
    };

    await expect(
      pool.call("agents.delegate", { agent: "data", message: "list tables" }, scope, "planner"),
    ).rejects.toThrow("only available to a running root task of a delegator");
  });

  it("rejects a delegator manifest that is itself delegatable", () => {
    expect(() => validateAgentPlugin(agent("loop", ["agents.delegate"], true))).toThrow(
      "may delegate only if it does not accept delegation",
    );
    expect(() => validateAgentPlugin(agent("planner", ["agents.delegate"], false))).not.toThrow();
  });
});
