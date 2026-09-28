import { Hono } from "hono";
import { describe, expect, it, vi } from "vitest";
import { AgentPool } from "../src/registry.js";
import { registerWebApi } from "../src/web-api.js";
import { issueWebSession, type WebAuthConfig } from "../src/web-auth.js";

describe("report session authorization", () => {
  const webAuth: WebAuthConfig = {
    mode: "session",
    secret: "local-report-test-signing-key-only",
    ttlSeconds: 60,
  };

  function fixture() {
    const query = vi.fn(async (sql: string) => {
      if (sql.includes("FROM web_users WHERE id")) {
        return { rows: [{ id: "owner", name: "Owner" }], rowCount: 1 };
      }
      return {
        rows: [
          {
            id: "report-1",
            title: "Report",
            markdown: "Private",
            created_at: "2026-09-26T00:00:00Z",
          },
        ],
        rowCount: 1,
      };
    });
    const app = new Hono();
    registerWebApi(app, {
      database: { query } as never,
      pluginRegistry: new AgentPool(),
      pool: {} as never,
      runtime: {} as never,
      webAuth,
    });
    return { app, query };
  }

  it("rejects a user header without a signed session before querying reports", async () => {
    const { app, query } = fixture();
    const response = await app.request("/api/reports/report-1", {
      headers: { "X-User-Id": "owner" },
    });
    expect(response.status).toBe(401);
    expect(query).not.toHaveBeenCalled();
  });

  it("binds report reads to the signed identity, not a supplied user header", async () => {
    const { app, query } = fixture();
    const response = await app.request("/api/reports/report-1", {
      headers: {
        Authorization: `Bearer ${issueWebSession("owner", webAuth)}`,
        "X-User-Id": "someone-else",
      },
    });
    expect(response.status).toBe(200);
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("user_id = $2"), [
      "report-1",
      "owner",
    ]);
  });
});

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
