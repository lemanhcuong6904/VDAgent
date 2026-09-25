import { describe, expect, it } from "vitest";
import { AgentPool } from "../src/registry.js";
import { McpToolPool } from "../src/tool-pool.js";
import { createAgentDelegationTool } from "../src/tools/agent-delegation.js";

describe("orchestrator delegation guardrails", () => {
  it("restricts delegation to the orchestrator and the four registered specialists", async () => {
    const pool = new McpToolPool();
    pool.register(
      createAgentDelegationTool({
        database: {} as never,
        pluginRegistry: new AgentPool(),
        pool,
        runtime: {} as never,
      }),
    );
    const scope = { userId: "user", spaceId: "space", signal: new AbortController().signal };

    expect(pool.forAgent("not-registered")).toEqual([]);
    expect(pool.forAgent("orchestrator").map(({ name }) => name)).toEqual(["agents.delegate"]);
    await expect(
      pool.call(
        "agents.delegate",
        { agent: "not-registered", message: "run tests" },
        scope,
        "orchestrator",
      ),
    ).rejects.toThrow("Invalid input");
    await expect(
      pool.call("agents.delegate", { agent: "data", message: "list tables" }, scope, "data"),
    ).rejects.toThrow("not authorized");
  });

  it("requires a running root task before it starts a child invocation", async () => {
    const pool = new McpToolPool();
    pool.register(
      createAgentDelegationTool({
        database: {} as never,
        pluginRegistry: new AgentPool(),
        pool,
        runtime: {} as never,
      }),
    );
    const scope = {
      userId: "user",
      spaceId: "space",
      agentId: "orchestrator",
      depth: 0,
      signal: new AbortController().signal,
    };

    await expect(
      pool.call(
        "agents.delegate",
        { agent: "data", message: "list tables" },
        scope,
        "orchestrator",
      ),
    ).rejects.toThrow("only available to a running orchestrator task");
  });
});
