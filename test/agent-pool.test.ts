import { Type } from "typebox";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentContext, AgentPlugin } from "../src/agent-contract.js";
import {
  AgentPool,
  createExternalAgentPlugin,
  loadAgentPool,
  loadExternalAgentPlugins,
} from "../src/registry.js";

const plugin: AgentPlugin = {
  descriptor: {
    id: "test.agent",
    version: "1.0.0",
    name: "Test agent",
    description: "Test plugin",
    input: Type.Object({ value: Type.String() }),
    tools: [],
  },
  async run() {
    return {};
  },
};

describe("AgentPool", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("registers one or more trusted module agents and rejects duplicate IDs", async () => {
    const pool = new AgentPool();
    pool.register(plugin);
    expect(pool.get("test.agent")?.descriptor).toMatchObject(plugin.descriptor);
    expect(pool.list().map(({ id }) => id)).toEqual(["test.agent"]);
    expect(() => pool.register(plugin)).toThrow("already registered");
    const loaded = await loadAgentPool(["test/fixtures/agent-plugin.ts"]);
    expect(loaded.list().map(({ id }) => id)).toContain("example.summary");
  });

  it("discovers agents by capability without knowing their concrete IDs", () => {
    const pool = new AgentPool();
    pool.register({
      descriptor: {
        id: "warehouse.specialist",
        version: "1.0.0",
        name: "Warehouse specialist",
        description: "Queries a warehouse",
        capabilities: ["warehouse.query"],
        input: Type.Object({}),
        tools: [],
      },
      async run() {
        return {};
      },
    });

    expect(pool.findByCapability("WAREHOUSE.QUERY").map(({ descriptor }) => descriptor.id)).toEqual(
      ["warehouse.specialist"],
    );
  });

  it("accepts a versioned external runtime manifest without importing backend modules", () => {
    const external = createExternalAgentPlugin({
      apiVersion: "agent-plugin.v2",
      id: "team.python.summary",
      version: "1.0.0",
      name: "Python summary",
      description: "Runs in a separate Python process.",
      capabilities: ["dataset.insight"],
      tools: ["warehouse.run_query"],
      inputSchema: {
        type: "object",
        properties: { prompt: { type: "string" } },
        required: ["prompt"],
      },
      command: "python",
      args: ["-m", "team_agent"],
    });
    const pool = new AgentPool();
    pool.register(external);
    expect(pool.findByCapability("dataset.insight").map(({ descriptor }) => descriptor.id)).toEqual(
      ["team.python.summary"],
    );
    expect(pool.get("team.python.summary")?.descriptor.apiVersion).toBe("agent-plugin.v2");
  });

  it("blocks external process agents in production until an isolated runtime is configured", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("AGENT_ISOLATION_MODE", "");
    await expect(loadExternalAgentPlugins(["unused-manifest.json"])).rejects.toThrow(
      "External agents require AGENT_ISOLATION_MODE=bwrap in production service mode",
    );
    const external = createExternalAgentPlugin({
      id: "team.python.summary",
      version: "1.0.0",
      name: "Python summary",
      description: "Runs in a separate Python process.",
      tools: [],
      inputSchema: { type: "object" },
      command: "python",
    });

    await expect(external.run({}, {} as AgentContext)).rejects.toThrow(
      "External agents require AGENT_ISOLATION_MODE=bwrap in production service mode",
    );
  });
});
