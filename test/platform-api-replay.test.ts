/**
 * API v1 semantics - M12.2
 * Reconnect/replay, idempotency under concurrency, error envelope and the legacy
 * adapter. The PostgreSQL block is the evidence for "reconnect/replay does not lose
 * events": it runs against the real ledger, not a mock.
 */

import { randomUUID } from "node:crypto";
import { Hono } from "hono";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { migrateDatabase } from "../src/database.js";
import {
  canonicalJson,
  legacySuccessor,
  registerLegacyAdapter,
  registerPlatformApi,
} from "../src/platform-api.js";
import { AgentPool } from "../src/registry.js";
import { IdempotencyConflictError, RunLedger } from "../src/run-ledger.js";
import { issueWebSession, type WebAuthConfig } from "../src/web-auth.js";

const webAuth: WebAuthConfig = {
  mode: "session",
  secret: "local-api-v1-replay-signing-key-only",
  ttlSeconds: 60,
};

type SseFrame = { id?: string; event?: string; data?: string };

function parseSse(text: string): SseFrame[] {
  return text
    .split("\n\n")
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const frame: SseFrame = {};
      for (const line of block.split("\n")) {
        const index = line.indexOf(":");
        if (index <= 0) continue;
        const field = line.slice(0, index);
        const value = line.slice(index + 1).replace(/^ /, "");
        if (field === "id" || field === "event" || field === "data") frame[field] = value;
      }
      return frame;
    });
}

describe("canonical fingerprint", () => {
  it("ignores object key order but not array order or values", () => {
    expect(canonicalJson({ a: 1, b: { d: 2, c: 3 } })).toBe(
      canonicalJson({ b: { c: 3, d: 2 }, a: 1 }),
    );
    expect(canonicalJson([1, 2])).not.toBe(canonicalJson([2, 1]));
    expect(canonicalJson({ a: 1 })).not.toBe(canonicalJson({ a: "1" }));
  });
});

describe("legacy adapter", () => {
  function app() {
    const query = vi.fn(async (sql: string) => {
      if (sql.includes("FROM web_users WHERE id")) return { rows: [{ id: "owner" }] };
      if (sql.includes("FROM web_tasks")) return { rows: [{ platform_run_id: "run_7" }] };
      return { rows: [] };
    });
    const hono = new Hono();
    const dependencies = { database: { query } as never, pluginRegistry: new AgentPool(), webAuth };
    registerLegacyAdapter(hono, dependencies);
    // Stand-in for a legacy route: the adapter must not alter its body or status.
    hono.get("/api/agents", (context) => context.json([{ id: "legacy" }], 200));
    hono.get("/api/users", (context) => context.json([], 200));
    registerPlatformApi(hono, dependencies);
    return { hono, query };
  }

  it("maps only routes that actually have a successor", () => {
    expect(legacySuccessor("/api/agents")).toBe("/api/v1/registry/agents");
    expect(legacySuccessor("/api/tasks/t1/cancel")).toBe("/api/v1/runs");
    expect(legacySuccessor("/api/users")).toBeUndefined();
    expect(legacySuccessor("/api/v1/runs")).toBeUndefined();
  });

  it("keeps the legacy body intact and advertises the successor", async () => {
    const { hono } = app();
    const response = await hono.request("/api/agents");
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual([{ id: "legacy" }]);
    expect(response.headers.get("deprecation")).toBe("true");
    expect(response.headers.get("link")).toBe('</api/v1/registry/agents>; rel="successor-version"');
  });

  it("leaves routes without a successor undecorated", async () => {
    const { hono } = app();
    const response = await hono.request("/api/users");
    expect(response.headers.get("deprecation")).toBeNull();
  });

  it("bridges a legacy task id to its run and cursor endpoints, scoped to the owner", async () => {
    const { hono, query } = app();
    const response = await hono.request("/api/v1/legacy/tasks/task_1/run", {
      headers: { Authorization: `Bearer ${issueWebSession("owner", webAuth)}` },
    });
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      task_id: "task_1",
      run_id: "run_7",
      events: "/api/v1/runs/run_7/events",
      stream: "/api/v1/runs/run_7/stream",
    });
    expect(query).toHaveBeenLastCalledWith(expect.stringContaining("user_id = $2"), [
      "task_1",
      "owner",
    ]);
  });

  it("answers an unknown v1 path with the v1 error envelope", async () => {
    const { hono } = app();
    const response = await hono.request("/api/v1/does-not-exist");
    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({
      error: { code: "route_not_found", message: "No such v1 resource" },
    });
  });
});

describe("run stream (mocked ledger)", () => {
  const RUN = {
    id: "run_1",
    status: "completed",
    attempt: "0",
    max_attempts: "1",
    created_at: "2026-09-27T12:00:00Z",
    updated_at: "2026-09-27T12:00:00Z",
  };

  function app(events: { seq: number }[]) {
    const eventsAfter = vi.fn(async (_runId: string, after: number) =>
      events
        .filter((event) => event.seq > after)
        .map((event) => ({
          run_id: "run_1",
          seq: String(event.seq),
          event_type: "run.status",
          payload: {},
          created_at: "2026-09-27T12:00:00Z",
        })),
    );
    const query = vi.fn(async (sql: string) => {
      if (sql.includes("FROM web_users WHERE id")) return { rows: [{ id: "owner" }] };
      if (sql.includes("FROM platform_runs WHERE id")) return { rows: [RUN] };
      return { rows: [] };
    });
    const hono = new Hono();
    registerPlatformApi(hono, {
      database: { query } as never,
      pluginRegistry: new AgentPool(),
      webAuth,
      runLedger: { eventsAfter } as never,
      streamPollMs: 5,
    });
    return { hono, eventsAfter };
  }

  const headers = () => ({ Authorization: `Bearer ${issueWebSession("owner", webAuth)}` });

  it("resumes from Last-Event-ID and ends with a terminal marker", async () => {
    const { hono, eventsAfter } = app([{ seq: 1 }, { seq: 2 }, { seq: 3 }]);
    const response = await hono.request("/api/v1/runs/run_1/stream", {
      headers: { ...headers(), "Last-Event-ID": "1" },
    });
    expect(response.headers.get("content-type")).toContain("text/event-stream");
    const frames = parseSse(await response.text());
    expect(frames.filter((frame) => frame.id).map((frame) => frame.id)).toEqual(["2", "3"]);
    expect(frames.at(-1)).toMatchObject({ event: "stream.end" });
    expect(JSON.parse(frames.at(-1)?.data ?? "{}")).toMatchObject({
      cursor: 3,
      status: "completed",
    });
    expect(eventsAfter).toHaveBeenCalledWith("run_1", 1, 200);
  });

  it("rejects a malformed Last-Event-ID", async () => {
    const { hono } = app([]);
    const response = await hono.request("/api/v1/runs/run_1/stream", {
      headers: { ...headers(), "Last-Event-ID": "-4" },
    });
    expect(response.status).toBe(422);
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("API v1 reconnect/replay - M12.2 (PostgreSQL)", () => {
  let database: Pool;
  let ledger: RunLedger;
  let hono: Hono;
  const userId = `user_${randomUUID().slice(0, 8)}`;
  const spaceId = `space_${randomUUID().slice(0, 8)}`;
  const foreignSpaceId = `space_${randomUUID().slice(0, 8)}`;

  beforeAll(async () => {
    database = new Pool({ connectionString: databaseUrl, max: 6 });
    await migrateDatabase(database);
    await database.query(
      "INSERT INTO web_users (id, name) VALUES ($1, $1) ON CONFLICT DO NOTHING",
      [userId],
    );
    ledger = new RunLedger(database);
    hono = new Hono();
    registerPlatformApi(hono, {
      database,
      pluginRegistry: new AgentPool(),
      webAuth,
      runLedger: ledger,
      spaceId,
      streamPollMs: 20,
    });
  });

  afterAll(async () => {
    await database?.query("DELETE FROM platform_runs WHERE space_id = ANY($1::text[])", [
      [spaceId, foreignSpaceId],
    ]);
    await database?.query("DELETE FROM web_users WHERE id = $1", [userId]);
    await database?.end();
  });

  const headers = (extra: Record<string, string> = {}) => ({
    Authorization: `Bearer ${issueWebSession(userId, webAuth)}`,
    "X-Space-Id": spaceId,
    "Content-Type": "application/json",
    ...extra,
  });

  async function createRun(key: string, input: unknown = { q: 1 }) {
    return hono.request("/api/v1/runs", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ workflow_id: "analytics", idempotency_key: key, input }),
    });
  }

  async function appendStatus(runId: string, to: string) {
    await ledger.appendEvent({ runId, spaceId, userId, eventType: "run.status", payload: { to } });
  }

  it("concurrent creates with one key yield one run and one run.queued event", async () => {
    const key = `key_${randomUUID()}`;
    const responses = await Promise.all(Array.from({ length: 5 }, () => createRun(key)));
    const bodies = (await Promise.all(responses.map((response) => response.json()))) as {
      run_id: string;
      replayed: boolean;
    }[];
    expect(new Set(bodies.map((body) => body.run_id)).size).toBe(1);
    expect(bodies.filter((body) => !body.replayed)).toHaveLength(1);
    expect(responses.map((response) => response.status).sort()).toEqual([200, 200, 200, 200, 202]);

    const queued = await database.query(
      "SELECT count(*)::int AS n FROM platform_run_events WHERE run_id = $1 AND event_type = 'run.queued'",
      [bodies[0].run_id],
    );
    expect(queued.rows[0].n).toBe(1);
  });

  it("refuses the same key with a different input and creates nothing", async () => {
    const key = `key_${randomUUID()}`;
    expect((await createRun(key, { q: 1 })).status).toBe(202);
    const conflict = await createRun(key, { q: 2 });
    expect(conflict.status).toBe(409);
    const runs = await database.query(
      "SELECT count(*)::int AS n FROM platform_runs WHERE space_id = $1 AND idempotency_key = $2",
      [spaceId, key],
    );
    expect(runs.rows[0].n).toBe(1);
  });

  it("binds an idempotency key to the original workflow and version", async () => {
    const key = `key_${randomUUID()}`;
    await ledger.create({
      spaceId,
      userId,
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      input: { q: 1 },
      idempotencyKey: key,
    });

    await expect(
      ledger.create({
        spaceId,
        userId,
        workflowId: "different-workflow",
        workflowVersion: "1.0.0",
        input: { q: 1 },
        idempotencyKey: key,
      }),
    ).rejects.toBeInstanceOf(IdempotencyConflictError);
  });

  it("makes an exhausted expired lease terminal and removes its worker lease", async () => {
    const created = await ledger.create({
      spaceId,
      userId,
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      input: {},
      idempotencyKey: `key_${randomUUID()}`,
    });
    // Exhaust the single configured attempt so an expired lease must become terminal.
    await database.query("UPDATE platform_runs SET max_attempts = 1 WHERE id = $1", [created.id]);
    await database.query(
      `UPDATE platform_runs SET status = 'failed', finished_at = now()
       WHERE space_id = $1 AND user_id = $2 AND status = 'queued' AND id <> $3`,
      [spaceId, userId, created.id],
    );
    const claimed = await ledger.claim("expired-worker", 30_000);
    expect(claimed?.id).toBe(created.id);
    await database.query(
      "UPDATE platform_runs SET lease_until = now() - interval '1 second' WHERE id = $1",
      [created.id],
    );

    await expect(ledger.claim("next-worker", 30_000)).resolves.toBeUndefined();
    const state = await database.query<{
      status: string;
      finished_at: Date | null;
      error: string | null;
      lease_count: string;
      previous_status: string;
      next_status: string;
    }>(
      `SELECT run.status, run.finished_at, run.error,
         (SELECT count(*) FROM platform_worker_leases lease WHERE lease.run_id = run.id)::text AS lease_count,
         event.payload->>'from' AS prior_status, event.payload->>'to' AS next_status
       FROM platform_runs run
       JOIN platform_run_events event ON event.run_id = run.id AND event.event_type = 'run.status'
       WHERE run.id = $1
       ORDER BY event.seq DESC LIMIT 1`,
      [created.id],
    );
    expect(state.rows[0]).toMatchObject({
      status: "failed",
      error: "Maximum attempts exceeded",
      lease_count: "0",
      prior_status: "leased",
      next_status: "failed",
    });
    expect(state.rows[0]?.finished_at).toBeInstanceOf(Date);
  });

  it("records queued cancellation as a terminal status event", async () => {
    const created = await ledger.create({
      spaceId,
      userId,
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      input: {},
      idempotencyKey: `key_${randomUUID()}`,
    });
    await expect(ledger.cancel(created.id, spaceId, userId)).resolves.toBe(true);
    const event = await database.query<{ from: string; to: string }>(
      `SELECT payload->>'from' AS prior_status, payload->>'to' AS next_status
       FROM platform_run_events WHERE run_id = $1 AND event_type = 'run.status'`,
      [created.id],
    );
    expect(event.rows.at(-1)).toEqual({ prior_status: "queued", next_status: "cancelled" });
  });

  it("a client that drops mid-run and reconnects sees every event exactly once", async () => {
    const created = (await (await createRun(`key_${randomUUID()}`)).json()) as { run_id: string };
    const runId = created.run_id;
    await appendStatus(runId, "leased");
    await appendStatus(runId, "running");

    // First connection: page through what exists, then "disconnect".
    const firstPage = (await (
      await hono.request(`/api/v1/runs/${runId}/events?after=0`, { headers: headers() })
    ).json()) as { events: { seq: number }[]; cursor: number };
    const seen = firstPage.events.map((event) => event.seq);

    // Events land while the client is away.
    await appendStatus(runId, "step.1");
    await appendStatus(runId, "step.2");

    // Reconnect on the live stream from the cursor; finish the run while it is open.
    const streamed = hono.request(`/api/v1/runs/${runId}/stream`, {
      headers: headers({ "Last-Event-ID": String(firstPage.cursor) }),
    });
    setTimeout(() => {
      void (async () => {
        await appendStatus(runId, "completed");
        await database.query(
          "UPDATE platform_runs SET status = 'completed', finished_at = now() WHERE id = $1",
          [runId],
        );
      })();
    }, 60);
    const frames = parseSse(await (await streamed).text());
    seen.push(...frames.filter((frame) => frame.id).map((frame) => Number(frame.id)));

    const all = await database.query<{ seq: string }>(
      "SELECT seq FROM platform_run_events WHERE run_id = $1 ORDER BY seq",
      [runId],
    );
    const expected = all.rows.map((row) => Number(row.seq));
    expect(expected.length).toBeGreaterThanOrEqual(5);
    // No gap and no duplicate across the disconnect.
    expect(seen).toEqual(expected);
    expect(frames.at(-1)).toMatchObject({ event: "stream.end" });
  });

  it("hides a run outside the deployment space with a 404", async () => {
    const foreignRun = await ledger.create({
      spaceId: foreignSpaceId,
      userId,
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      input: {},
      idempotencyKey: `key_${randomUUID()}`,
    });
    const response = await hono.request(`/api/v1/runs/${foreignRun.id}/stream`, {
      headers: headers(),
    });
    expect(response.status).toBe(404);
  });
});
