/**
 * Versioned API v1 Tests - M12.1
 * Scope enforcement, cursor replay, idempotency and the negative cases that
 * matter: an unscoped caller must never reach another tenant's runs or evidence.
 */

import { Hono } from "hono";
import { describe, expect, it, vi } from "vitest";
import { registerPlatformApi } from "../src/platform-api.js";
import { AgentPool } from "../src/registry.js";
import { issueWebSession, type WebAuthConfig } from "../src/web-auth.js";

const webAuth: WebAuthConfig = {
  mode: "session",
  secret: "local-api-v1-test-signing-key-only",
  ttlSeconds: 60,
};

type QueryResult = { rows: unknown[]; rowCount?: number };

function fixture(
  handler: (sql: string, params: unknown[]) => QueryResult,
  ledger?: Record<string, unknown>,
) {
  const query = vi.fn(async (sql: string, params: unknown[] = []) => {
    if (sql.includes("FROM web_users WHERE id")) {
      return { rows: [{ id: "owner", name: "Owner" }], rowCount: 1 } as never;
    }
    return handler(sql, params) as never;
  });
  const app = new Hono();
  registerPlatformApi(app, {
    database: { query } as never,
    pluginRegistry: new AgentPool(),
    webAuth,
    spaceId: "space_a",
    runLedger: ledger as never,
  });
  return { app, query };
}

function authorize(userId = "owner", spaceId?: string) {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${issueWebSession(userId, webAuth)}`,
  };
  if (spaceId) headers["X-Space-Id"] = spaceId;
  return headers;
}

const RUN_ROW = {
  id: "run_1",
  space_id: "space_a",
  user_id: "owner",
  workflow_id: "analytics",
  workflow_version: "1.0.0",
  status: "running",
  error: null,
  attempt: "0",
  max_attempts: "1",
  cancel_requested: false,
  worker_id: "worker-a",
  lease_until: "2026-09-27T12:00:05Z",
  deadline_at: null,
  created_at: "2026-09-27T12:00:00Z",
  updated_at: "2026-09-27T12:00:01Z",
  finished_at: null,
};

describe("api v1 - authentication and scope", () => {
  it("rejects a caller with no session before touching the database", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/runs", {
      headers: { "X-User-Id": "owner", "X-Space-Id": "space_a" },
    });
    expect(response.status).toBe(401);
    expect(query).not.toHaveBeenCalled();
  });

  it("rejects a signed session for an unknown user", async () => {
    const query = vi.fn(async () => ({ rows: [] }));
    const app = new Hono();
    registerPlatformApi(app, {
      database: { query } as never,
      pluginRegistry: new AgentPool(),
      webAuth,
    });
    const response = await app.request("/api/v1/runs", { headers: authorize("ghost") });
    expect(response.status).toBe(401);
    expect(query).toHaveBeenCalledTimes(1);
  });

  it("protects registry and activation routes that only project configured metadata", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    for (const [path, method] of [
      ["/api/v1/registry/agents", "GET"],
      ["/api/v1/activation/agents", "GET"],
      ["/api/v1/activation/agents/analytics/1.0.0", "POST"],
    ]) {
      const response = await app.request(path, {
        method,
        headers: { "X-User-Id": "owner" },
      });
      expect(response.status).toBe(401);
      await expect(response.json()).resolves.toMatchObject({
        error: { code: "authentication_required" },
      });
    }
    expect(query).not.toHaveBeenCalled();
  });

  it("authenticates the activation mutation before returning not-supported", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/activation/agents/analytics/1.0.0", {
      method: "POST",
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(501);
    expect(query).toHaveBeenCalledWith("SELECT id FROM web_users WHERE id = $1", ["owner"]);
  });

  it("fails closed when platform auth configuration is omitted", async () => {
    const query = vi.fn(async () => ({ rows: [{ id: "owner" }] }));
    const app = new Hono();
    registerPlatformApi(app, {
      database: { query } as never,
      pluginRegistry: new AgentPool(),
    });
    const response = await app.request("/api/v1/registry/agents", {
      headers: { "X-User-Id": "owner" },
    });
    expect(response.status).toBe(401);
    expect(query).not.toHaveBeenCalled();
  });

  it("binds the run list to the signed identity and the requested space", async () => {
    const { app, query } = fixture(() => ({ rows: [RUN_ROW] }));
    const response = await app.request("/api/v1/runs", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as { runs: { run_id: string; attempt: number }[] };
    expect(body.runs[0].run_id).toBe("run_1");
    // bigint/numeric columns arrive as strings and must be surfaced as numbers.
    expect(body.runs[0].attempt).toBe(0);
    expect(query).toHaveBeenLastCalledWith(
      expect.stringContaining("space_id = $1 AND user_id = $2"),
      ["space_a", "owner", null, 50],
    );
  });

  it("rejects a caller-selected space that is not the configured deployment space", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/runs", {
      headers: authorize("owner", "another-users-space"),
    });
    expect(response.status).toBe(401);
    expect(query).not.toHaveBeenCalledWith(
      expect.stringContaining("FROM platform_runs"),
      expect.anything(),
    );
  });

  it("clamps a hostile limit instead of trusting it", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    await app.request("/api/v1/runs?limit=100000", { headers: authorize("owner", "space_a") });
    expect(query).toHaveBeenLastCalledWith(expect.any(String), ["space_a", "owner", null, 200]);
  });

  it("does not leak a run belonging to another user", async () => {
    const { app } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/runs/run_other", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(404);
  });
});

describe("api v1 - run creation and cancellation", () => {
  /** `existingRun` simulates a prior row under the same key, as ON CONFLICT would return it. */
  function createFixture(
    existingRun:
      | { id: string; workflow_id: string; workflow_version: string; input: unknown }
      | undefined,
  ) {
    const create = vi.fn(async (input: { id: string }) => ({
      id: existingRun?.id ?? input.id,
      status: "queued",
      attempt: 0,
      fencing_token: "0",
      created_at: new Date("2026-09-27T12:00:00Z"),
    }));
    const cancel = vi.fn(async () => true);
    const fixtureResult = fixture(
      (sql) => {
        if (sql.includes("SELECT workflow_id, workflow_version, input, status")) {
          return { rows: existingRun ? [{ ...existingRun, status: "running" }] : [] };
        }
        return { rows: [] };
      },
      { create, cancel },
    );
    return { ...fixtureResult, create, cancel };
  }

  function post(body: unknown, headers: Record<string, string> = {}) {
    return {
      method: "POST" as const,
      headers: { ...authorize("owner", "space_a"), "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    };
  }

  it("requires an idempotency key before reaching the ledger", async () => {
    const { app, create } = createFixture(undefined);
    const response = await app.request("/api/v1/runs", post({ workflow_id: "analytics" }));
    expect(response.status).toBe(422);
    expect(create).not.toHaveBeenCalled();
  });

  it("queues a new run with 202 and reports that it was not a replay", async () => {
    const { app, create } = createFixture(undefined);
    const response = await app.request(
      "/api/v1/runs",
      post({ workflow_id: "analytics", idempotency_key: "key-1" }),
    );
    expect(response.status).toBe(202);
    const body = (await response.json()) as { run_id: string; status: string; replayed: boolean };
    expect(body).toMatchObject({ status: "queued", replayed: false });
    expect(body.run_id).toMatch(/^run_[0-9a-f]{16}$/);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("answers a repeated key with the original run instead of a second one", async () => {
    const { app, create } = createFixture({
      id: "run_original",
      workflow_id: "analytics",
      workflow_version: "1.0.0",
      // jsonb does not keep key order; the fingerprint must not care.
      input: { b: 2, a: 1 },
    });
    const response = await app.request(
      "/api/v1/runs",
      post({
        workflow_id: "analytics",
        idempotency_key: "key-1",
        input: { a: 1, b: 2 },
      }),
    );
    // A replay is a success, not a conflict: the caller gets 200 and the same run.
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      run_id: "run_original",
      status: "running",
      replayed: true,
    });
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("rejects a reused key carrying a different request", async () => {
    const { app } = createFixture({
      id: "run_original",
      workflow_id: "analytics",
      workflow_version: "1.0.0",
      input: { a: 1 },
    });
    const response = await app.request(
      "/api/v1/runs",
      post({ workflow_id: "analytics", idempotency_key: "key-1", input: { a: 2 } }),
    );
    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "idempotency_conflict" },
    });
  });

  it("separates malformed JSON (400) from a wrong shape (422)", async () => {
    const { app, create } = createFixture(undefined);
    const malformed = await app.request("/api/v1/runs", {
      method: "POST",
      headers: { ...authorize("owner", "space_a"), "Content-Type": "application/json" },
      body: "{not json",
    });
    expect(malformed.status).toBe(400);
    const wrongShape = await app.request("/api/v1/runs", post({ workflow: 1 }));
    expect(wrongShape.status).toBe(422);
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects an over-long idempotency key before reaching the ledger", async () => {
    const { app, create } = createFixture(undefined);
    const response = await app.request(
      "/api/v1/runs",
      post({ workflow_id: "analytics", idempotency_key: "k".repeat(257) }),
    );
    expect(response.status).toBe(422);
    expect(create).not.toHaveBeenCalled();
  });

  it("accepts the key from the header as well as the body", async () => {
    const { app, create } = createFixture(undefined);
    const response = await app.request(
      "/api/v1/runs",
      post({ workflow_id: "analytics" }, { "Idempotency-Key": "header-key" }),
    );
    expect(response.status).toBe(202);
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ idempotencyKey: "header-key" }));
  });

  it("reports a refused cancellation as a conflict", async () => {
    const cancel = vi.fn(async () => false);
    const { app } = fixture(() => ({ rows: [] }), { cancel });
    const response = await app.request("/api/v1/runs/run_1/cancel", {
      method: "POST",
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(409);
  });

  it("passes the caller's space and identity to the ledger on cancel", async () => {
    const cancel = vi.fn(async () => true);
    const { app } = fixture(() => ({ rows: [] }), { cancel });
    const response = await app.request("/api/v1/runs/run_1/cancel", {
      method: "POST",
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(200);
    expect(cancel).toHaveBeenCalledWith("run_1", "space_a", "owner");
  });
});

describe("api v1 - step and event projections", () => {
  const STEP_ROW = {
    id: "step_1",
    parent_step_id: null,
    kind: "tool",
    agent_id: "analytics",
    capability: "sql.query",
    status: "completed",
    attempt: "0",
    error: null,
    has_input: true,
    has_output: true,
    created_at: "2026-09-27T12:00:00Z",
    started_at: "2026-09-27T12:00:00Z",
    finished_at: "2026-09-27T12:00:02Z",
  };

  it("never serializes a step body, only the fact that one exists", async () => {
    const { app } = fixture((sql) => {
      if (sql.includes("FROM platform_runs WHERE id")) return { rows: [RUN_ROW] };
      return { rows: [STEP_ROW] };
    });
    const response = await app.request("/api/v1/runs/run_1/steps", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(200);
    const text = JSON.stringify(await response.json());
    expect(text).toContain('"has_input":true');
    expect(text).not.toContain("SELECT * FROM");
    // The projection must not carry the raw column names a client could mistake for content.
    expect(text).not.toMatch(/"input"|"output"/);
  });

  it("scopes a step lookup through its parent run", async () => {
    const { app, query } = fixture(() => ({ rows: [STEP_ROW] }));
    const response = await app.request("/api/v1/steps/step_1", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(200);
    expect(query).toHaveBeenLastCalledWith(
      expect.stringContaining("JOIN platform_runs r ON r.id = s.run_id"),
      ["step_1", "space_a", "owner"],
    );
  });
});

describe("api v1 - event cursor replay", () => {
  const events = [
    {
      run_id: "run_1",
      seq: "3",
      event_type: "run.status",
      payload: { to: "running" },
      created_at: "2026-09-27T12:00:03Z",
    },
    {
      run_id: "run_1",
      seq: "4",
      event_type: "run.status",
      payload: { to: "completed" },
      created_at: "2026-09-27T12:00:04Z",
    },
  ];

  it("replays only events after the supplied cursor and returns the new cursor", async () => {
    const { app, query } = fixture((sql) => {
      if (sql.includes("FROM platform_runs WHERE id")) return { rows: [RUN_ROW] };
      return { rows: events };
    });
    const response = await app.request("/api/v1/runs/run_1/events?after=2", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(200);
    const body = (await response.json()) as { events: { seq: number }[]; cursor: number };
    expect(body.events.map((event) => event.seq)).toEqual([3, 4]);
    expect(body.cursor).toBe(4);
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("seq > $2 ORDER BY seq ASC"), [
      "run_1",
      2,
      50,
    ]);
  });

  it("treats a missing cursor as the beginning of the stream", async () => {
    const { app, query } = fixture((sql) => {
      if (sql.includes("FROM platform_runs WHERE id")) return { rows: [RUN_ROW] };
      return { rows: [] };
    });
    const response = await app.request("/api/v1/runs/run_1/events", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(200);
    expect(query).toHaveBeenLastCalledWith(expect.any(String), ["run_1", 0, 50]);
  });

  it("rejects a malformed cursor rather than defaulting silently", async () => {
    const { app } = fixture((sql) => {
      if (sql.includes("FROM platform_runs WHERE id")) return { rows: [RUN_ROW] };
      return { rows: [] };
    });
    const response = await app.request("/api/v1/runs/run_1/events?after=abc", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(422);
  });

  it("does not replay events for a run outside the caller's scope", async () => {
    const { app } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/runs/run_other/events", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(404);
  });
});

describe("api v1 - evidence and artifacts stay inside the space", () => {
  it("delegates the workspace filter to the storage layer", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    await app.request("/api/v1/evidence/ev_1", { headers: authorize("owner", "space_a") });
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("workspace_id = $2"), [
      "ev_1",
      "space_a",
      "owner",
    ]);
  });

  it("binds direct evidence and artifact reads to the signed user", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    const headers = authorize("owner", "space_a");
    expect((await app.request("/api/v1/evidence/ev_other", { headers })).status).toBe(404);
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("web_invocations"), [
      "ev_other",
      "space_a",
      "owner",
    ]);

    expect((await app.request("/api/v1/artifacts/dat_other/content", { headers })).status).toBe(
      404,
    );
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("owner_user_id = $3"), [
      "dat_other",
      "space_a",
      "owner",
    ]);
  });

  it("returns 404 for an artifact in another workspace", async () => {
    const { app } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/artifacts/dat_other", {
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(404);
  });
});

describe("api v1 - metadata and unsupported mutations", () => {
  it("advertises the resource families and limits", async () => {
    const { app } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/meta");
    expect(response.status).toBe(200);
    const body = (await response.json()) as { api_version: string; resources: string[] };
    expect(body.api_version).toBe("v1");
    expect(body.resources).toContain("evidence");
    expect(body.resources).toContain("checkpoint");
  });

  it("refuses an activation mutation rather than faking it", async () => {
    const { app, query } = fixture(() => ({ rows: [] }));
    const response = await app.request("/api/v1/activation/agents/analytics/2.0.0", {
      method: "POST",
      headers: authorize("owner", "space_a"),
    });
    expect(response.status).toBe(501);
    expect(query).toHaveBeenCalledWith("SELECT id FROM web_users WHERE id = $1", ["owner"]);
  });
});
