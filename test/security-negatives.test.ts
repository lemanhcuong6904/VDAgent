/**
 * Browser/API security negatives and unknown-field compatibility - M12.6
 * Each test states an attack or a drift and shows it fails closed. The app is built
 * with the same `applyHttpSecurity` the server mounts.
 */

import { createHash } from "node:crypto";
import { Hono } from "hono";
import { Type } from "typebox";
import { describe, expect, it, vi } from "vitest";
import { registerA2aGateway } from "../src/a2a-gateway.js";
import { applyHttpSecurity, MAX_BODY_BYTES } from "../src/http-security.js";
import { handleMcpRequest } from "../src/mcp-server.js";
import { registerLegacyAdapter, registerPlatformApi } from "../src/platform-api.js";
import { AgentPool } from "../src/registry.js";
import { McpToolPool } from "../src/tool-pool.js";
import { registerWebApi } from "../src/web-api.js";
import { createWebAuth, issueWebSession, type WebAuthConfig } from "../src/web-auth.js";

const ORIGIN = "https://app.example";
const webAuth: WebAuthConfig = {
  mode: "session",
  secret: "local-security-negatives-signing-key",
  ttlSeconds: 60,
};

type Query = (sql: string) => Promise<{ rows: unknown[] }>;

const defaultQuery: Query = async (sql) =>
  sql.includes("FROM web_users WHERE id")
    ? { rows: [{ id: "owner", name: "Owner" }] }
    : { rows: [] };

function app(query = vi.fn(defaultQuery)) {
  const hono = new Hono();
  applyHttpSecurity(hono, { allowedOrigin: ORIGIN });
  const dependencies = { database: { query } as never, pluginRegistry: new AgentPool(), webAuth };
  registerLegacyAdapter(hono, dependencies);
  registerWebApi(hono, { ...dependencies, pool: {} as never, runtime: {} as never });
  registerPlatformApi(hono, dependencies);
  return { hono, query };
}

const bearer = (token: string) => ({ Authorization: `Bearer ${token}` });

describe("session tokens", () => {
  const valid = issueWebSession("owner", webAuth);

  it("rejects an expired session", async () => {
    const expired = issueWebSession("owner", webAuth, Math.floor(Date.now() / 1000) - 3_600);
    const { hono, query } = app();
    expect((await hono.request("/api/v1/runs", { headers: bearer(expired) })).status).toBe(401);
    expect(query).not.toHaveBeenCalled();
  });

  it("rejects a session whose user id was swapped after signing", async () => {
    const [prefix, version, , expiry, signature] = valid.split(".");
    const forged = [prefix, version, "admin", expiry, signature].join(".");
    const { hono, query } = app();
    expect((await hono.request("/api/v1/runs", { headers: bearer(forged) })).status).toBe(401);
    expect(query).not.toHaveBeenCalled();
  });

  it("rejects a session signed with another secret", async () => {
    const other = issueWebSession("owner", {
      ...webAuth,
      secret: "attacker-controlled-signing-key-xx",
    });
    const { hono } = app();
    expect((await hono.request("/api/v1/runs", { headers: bearer(other) })).status).toBe(401);
  });

  it("does not accept the session as a query parameter, where it would leak into logs", async () => {
    const { hono } = app();
    expect((await hono.request(`/api/v1/runs?token=${valid}&access_token=${valid}`)).status).toBe(
      401,
    );
  });

  it("ignores X-User-Id impersonation in session mode on both surfaces", async () => {
    const { hono } = app();
    expect((await hono.request("/api/v1/runs", { headers: { "X-User-Id": "owner" } })).status).toBe(
      401,
    );
    expect((await hono.request("/api/tasks", { headers: { "X-User-Id": "owner" } })).status).toBe(
      401,
    );
  });
});

describe("web auth startup configuration", () => {
  it("defaults production to signed sessions and requires a strong configured secret", () => {
    expect(() => createWebAuth({ NODE_ENV: "production" })).toThrow(/WEB_AUTH_SECRET must be/);
    expect(
      createWebAuth({
        NODE_ENV: "production",
        WEB_AUTH_SECRET: "a-production-session-signing-secret-with-enough-entropy",
      }).mode,
    ).toBe("session");
    expect(() =>
      createWebAuth({
        NODE_ENV: "production",
        WEB_AUTH_SECRET: "short-secret",
      }),
    ).toThrow(/at least 32 characters/);
  });

  it("refuses explicit demo auth and invalid modes in production", () => {
    expect(() =>
      createWebAuth({
        NODE_ENV: "production",
        WEB_AUTH_MODE: "demo",
        WEB_AUTH_SECRET: "a-production-session-signing-secret-with-enough-entropy",
      }),
    ).toThrow(/WEB_AUTH_MODE=session is required in production/);
    expect(() => createWebAuth({ WEB_AUTH_MODE: "typo" })).toThrow(/WEB_AUTH_MODE must be/);
  });
});

describe("v1 registry and activation authorization", () => {
  it("requires a signed session for collection reads and activation attempts", async () => {
    const { hono, query } = app();
    const requests: [string, RequestInit?][] = [
      ["/api/v1/registry/agents"],
      ["/api/v1/activation/agents"],
      [
        "/api/v1/activation/agents/analytics/1.0.0",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      ],
    ];
    for (const [path, init] of requests) {
      const response = await hono.request(path, init);
      expect(response.status).toBe(401);
      await expect(response.json()).resolves.toMatchObject({
        error: { code: "authentication_required" },
      });
    }
    expect(query).not.toHaveBeenCalled();
  });

  it("still resolves the signed user before returning registry data", async () => {
    const { hono, query } = app();
    const response = await hono.request("/api/v1/registry/agents", {
      headers: bearer(issueWebSession("owner", webAuth)),
    });
    expect(response.status).toBe(200);
    expect(query).toHaveBeenCalledWith("SELECT id FROM web_users WHERE id = $1", ["owner"]);
  });
});

describe("browser cross-origin", () => {
  it("does not grant a foreign origin read access", async () => {
    const { hono } = app();
    const response = await hono.request("/api/v1/meta", {
      headers: { Origin: "https://evil.example" },
    });
    expect(response.headers.get("access-control-allow-origin")).not.toBe("https://evil.example");
    expect(response.headers.get("access-control-allow-origin")).not.toBe("*");
  });

  it("answers the allowed origin's preflight with the v1 and A2A headers", async () => {
    const { hono } = app();
    const response = await hono.request("/api/v1/runs", {
      method: "OPTIONS",
      headers: {
        Origin: ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,idempotency-key,x-space-id",
      },
    });
    expect(response.headers.get("access-control-allow-origin")).toBe(ORIGIN);
    const allowed = (response.headers.get("access-control-allow-headers") ?? "").toLowerCase();
    for (const header of [
      "authorization",
      "idempotency-key",
      "x-space-id",
      "last-event-id",
      "a2a-version",
    ]) {
      expect(allowed).toContain(header);
    }
  });

  it("exposes the migration headers so a browser client can read them", async () => {
    const { hono } = app();
    const response = await hono.request("/api/v1/meta", { headers: { Origin: ORIGIN } });
    expect((response.headers.get("access-control-expose-headers") ?? "").toLowerCase()).toContain(
      "link",
    );
  });

  it("sends clickjacking and sniffing protections on API responses", async () => {
    const { hono } = app();
    const response = await hono.request("/api/v1/meta");
    expect(response.headers.get("x-frame-options")).toBe("SAMEORIGIN");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("strict-transport-security")).toContain("max-age");
  });
});

describe("request shape", () => {
  it("refuses an oversized body with the error envelope before any handler", async () => {
    const { hono, query } = app();
    const response = await hono.request("/api/v1/runs", {
      method: "POST",
      headers: {
        ...bearer(issueWebSession("owner", webAuth)),
        "Content-Type": "application/json",
        "Content-Length": String(MAX_BODY_BYTES + 1),
      },
      body: "x".repeat(MAX_BODY_BYTES + 1),
    });
    expect(response.status).toBe(413);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "payload_too_large" } });
    expect(query).not.toHaveBeenCalled();
  });

  it("refuses identifiers carrying SQL or path syntax before they reach a query", async () => {
    const { hono, query } = app();
    for (const space of ["a' OR '1'='1", "../other", "a b"]) {
      const response = await hono.request("/api/v1/runs", {
        headers: { ...bearer(issueWebSession("owner", webAuth)), "X-Space-Id": space },
      });
      expect(response.status).toBe(401);
    }
    const reachedRuns = query.mock.calls.some(([sql]) =>
      String(sql).includes("FROM platform_runs"),
    );
    expect(reachedRuns).toBe(false);
  });
});

describe("artifact download", () => {
  it("serves bytes as an inert attachment, never inline", async () => {
    const query = vi.fn<Query>(async (sql) => {
      if (sql.includes("FROM web_users WHERE id")) return { rows: [{ id: "owner" }] };
      if (sql.includes("artifact_contents"))
        return { rows: [{ content: Buffer.from("<script>alert(1)</script>") }] };
      if (sql.includes("FROM artifacts")) {
        return {
          rows: [
            {
              id: "dat_1",
              workspace_id: "local-space",
              owner_run_id: "run_1",
              kind: "report",
              version: "1",
              status: "ready",
              sha256: "x",
              bytes: "25",
              metadata: {},
              created_at: new Date(),
              ready_at: new Date(),
            },
          ],
        };
      }
      return { rows: [] };
    });
    const { hono } = app(query);
    const response = await hono.request("/api/v1/artifacts/dat_1/content", {
      headers: bearer(issueWebSession("owner", webAuth)),
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/octet-stream");
    expect(response.headers.get("content-disposition")).toMatch(/^attachment;/);
    expect(response.headers.get("content-security-policy")).toContain("sandbox");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  });
});

describe("unknown-field compatibility on external surfaces", () => {
  it("v1 POST /runs ignores unknown body fields and cannot set scope through them", async () => {
    const create = vi.fn(async (input: { id: string }) => ({
      id: input.id,
      status: "queued",
      attempt: 0,
      fencing_token: "0",
      created_at: new Date(),
    }));
    const query = vi.fn(async (sql: string) =>
      sql.includes("FROM web_users WHERE id") ? { rows: [{ id: "owner" }] } : { rows: [] },
    );
    const hono = new Hono();
    registerPlatformApi(hono, {
      database: { query } as never,
      pluginRegistry: new AgentPool(),
      webAuth,
      spaceId: "space_a",
      runLedger: { create } as never,
    });
    const response = await hono.request("/api/v1/runs", {
      method: "POST",
      headers: {
        ...bearer(issueWebSession("owner", webAuth)),
        "Content-Type": "application/json",
        "X-Space-Id": "space_a",
      },
      body: JSON.stringify({
        workflow_id: "analytics",
        idempotency_key: "k1",
        future_field: { nested: true },
        user_id: "admin",
        space_id: "space_admin",
      }),
    });
    expect(response.status).toBe(202);
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: "owner", spaceId: "space_a" }),
    );
  });

  it("MCP ignores unknown params on a known method", async () => {
    const pool = new McpToolPool();
    pool.register({
      name: "echo",
      description: "Echo",
      schema: Type.Object({ value: Type.String() }),
      mutates: false,
      agents: ["analytics"],
      authorize: () => true,
      execute: async (input) => input,
    });
    const response = await handleMcpRequest(
      new Request("http://localhost/mcp", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "application/json, text/event-stream",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
          params: { futureHint: "x" },
        }),
      }),
      { agentId: "analytics", userId: "u", spaceId: "s", allowedTools: ["echo"], pool },
    );
    const body = (await response.json()) as { result: { tools: unknown[] } };
    expect(body.result.tools).toHaveLength(1);
  });

  it("A2A tolerates unknown message fields but still takes scope from config", async () => {
    const connect = vi.fn(async () => {
      throw new Error("stop here");
    });
    const hono = new Hono();
    const registry = new AgentPool();
    registry.register({
      descriptor: {
        id: "analytics",
        version: "1",
        name: "A",
        description: "A",
        input: Type.Object({}),
        tools: [],
      },
      async run() {
        return {};
      },
    });
    registerA2aGateway(hono, {
      database: { query: vi.fn(), connect } as never,
      pluginRegistry: registry,
      runLedger: {} as never,
      clients: [
        {
          id: "p",
          tokenSha256: createHash("sha256").update("tok").digest("hex"),
          userId: "u",
          spaceId: "s",
          skills: ["analytics"],
          rateLimit: 60,
        },
      ],
      publicUrl: "http://localhost",
    });
    const response = await hono.request("/a2a", {
      method: "POST",
      headers: { authorization: "Bearer tok", "a2a-version": "1.0" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "SendMessage",
        params: {
          message: {
            messageId: "m1",
            role: "ROLE_USER",
            parts: [{ text: "hi", futurePartField: 1 }],
            extensions: ["urn:x"],
          },
          configuration: { acceptedOutputModes: ["text/plain"], futureConfig: true },
        },
      }),
    });
    // Validation passed and the gateway reached the database step; unknown fields were not a reason to refuse.
    expect(connect).toHaveBeenCalled();
    await expect(response.json()).resolves.toMatchObject({ error: { code: -32603 } });
  });
});
