import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import type { AgentPlugin } from "../src/agent-contract.js";
import { AgentPool, loadAgentPool } from "../src/registry.js";

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
  it("registers one or more trusted module agents and rejects duplicate IDs", async () => {
    const pool = new AgentPool();
    pool.register(plugin);
    expect(pool.get("test.agent")?.descriptor).toMatchObject(plugin.descriptor);
    expect(pool.list().map(({ id }) => id)).toEqual(["test.agent"]);
    expect(() => pool.register(plugin)).toThrow("already registered");
    const loaded = await loadAgentPool(["test/fixtures/agent-plugin.ts"]);
    expect(loaded.list().map(({ id }) => id)).toContain("example.summary");
  });
});
