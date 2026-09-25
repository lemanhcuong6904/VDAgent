import { Hono } from "hono";
import { describe, expect, it, vi } from "vitest";
import { AgentPool } from "../src/registry.js";
import { registerWebApi } from "../src/web-api.js";

describe("web API message pagination", () => {
  it("accepts the default cursor above PostgreSQL integer range", async () => {
    const query = vi.fn(async (sql: string) => {
      if (sql.includes("FROM web_users WHERE id")) {
        return { rows: [{ id: "user-1", name: "Test" }], rowCount: 1 };
      }
      return { rows: [], rowCount: 0 };
    });
    const agents = new AgentPool();
    agents.register({
      descriptor: {
        id: "example",
        version: "1",
        name: "Example",
        description: "Example agent",
        input: {},
        tools: [],
      },
      run: async () => ({}),
    });
    const app = new Hono();
    registerWebApi(app, {
      database: { query } as never,
      pluginRegistry: agents,
      pool: {} as never,
      runtime: {} as never,
    });

    const response = await app.request("/api/agents/example/messages", {
      headers: { "X-User-Id": "user-1" },
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ summary: null, messages: [], pending: [] });
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("seq < $3::bigint"), [
      "user-1",
      "example",
      Number.MAX_SAFE_INTEGER,
      50,
    ]);
  });
});
