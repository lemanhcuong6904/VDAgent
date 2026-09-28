import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { migrateDatabase } from "../src/database.js";
import { PostgresAgentMemoryProvider, PostgresMemoryAuditWriter } from "../src/postgres-store.js";

const databaseUrl = process.env.TEST_DATABASE_URL;
const integration = describe.skipIf(!databaseUrl);
let database: Pool;

describe("PostgreSQL memory purge limits", () => {
  it("uses safe bounded defaults for invalid audit purge limits", async () => {
    for (const limit of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1, 1.5]) {
      const query = vi.fn(async (_sql: string, _values?: unknown[]) => ({ rowCount: 0, rows: [] }));
      const pool = { query } as unknown as Pool;

      await new PostgresMemoryAuditWriter(pool).purgeExpired(limit);

      expect(query.mock.calls[0]?.[1]).toEqual([10_000]);
    }
  });

  it("uses safe bounded defaults for invalid agent memory purge limits", async () => {
    for (const limit of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1, 1.5]) {
      const query = vi.fn(async (_sql: string, _values?: unknown[]) => ({ rowCount: 0, rows: [] }));
      const pool = { query } as unknown as Pool;

      await new PostgresAgentMemoryProvider(pool).purgeExpired(limit);

      expect(query.mock.calls).toHaveLength(2);
      expect(query.mock.calls[0]?.[1]).toEqual([1000]);
      expect(query.mock.calls[1]?.[1]).toEqual([1000]);
    }
  });
});

beforeAll(async () => {
  if (!databaseUrl) return;
  database = new Pool({ connectionString: databaseUrl, max: 4 });
  await migrateDatabase(database);
});

afterAll(async () => {
  await database?.end();
});

integration("Postgres memory persistence and retention", () => {
  it("persists memory audit records and purges expired records", async () => {
    const workspaceId = `space_${randomUUID()}`;
    const writer = new PostgresMemoryAuditWriter(database, { retentionDays: 1 });
    await writer.recordAudit({
      workspaceId,
      operation: "commit",
      actor: "user/agent",
      resource: "memory-1",
      details: { content: "must not be retained in audit details" },
      success: true,
    });
    const rows = await writer.queryAudit(workspaceId);
    expect(rows).toHaveLength(1);
    expect(rows[0].details).toEqual({ content: "[redacted]" });
    await database.query(
      "UPDATE memory_audit_events SET expires_at = now() WHERE workspace_id = $1",
      [workspaceId],
    );
    expect(await writer.purgeExpired()).toBeGreaterThanOrEqual(1);
    expect(await writer.queryAudit(workspaceId)).toEqual([]);
  });

  it("does not return expired agent memory and supports bounded cleanup", async () => {
    const provider = new PostgresAgentMemoryProvider(database);
    const scope = {
      spaceId: `space_${randomUUID()}`,
      userId: "user-1",
      agentId: "agent-1",
      signal: new AbortController().signal,
    };
    await provider.remember(
      {
        key: "expired",
        text: "expired note",
        tags: ["retention-test"],
      },
      scope,
    );
    await database.query(
      "UPDATE agent_memory_entries SET expires_at = now() WHERE space_id = $1 AND memory_key = $2",
      [scope.spaceId, "expired"],
    );
    expect(await provider.search("expired", scope)).toEqual([]);
    expect(await provider.purgeExpired()).toBeGreaterThanOrEqual(1);
  });

  it("forgets by exact memory key inside the caller's space, user and agent", async () => {
    const provider = new PostgresAgentMemoryProvider(database);
    const scope = {
      spaceId: `space_${randomUUID()}`,
      userId: "owner",
      agentId: "agent-1",
      signal: new AbortController().signal,
    };
    const otherScope = { ...scope, userId: "other" };
    await provider.remember({ key: "public-note-key", text: "content with no identifier" }, scope);
    expect(await provider.search("identifier", scope)).toHaveLength(1);
    expect(await provider.search("public-note-key", scope)).toEqual([]);
    expect(await provider.forget("public-note-key", otherScope)).toBe(false);
    expect(await provider.forget("public-note-key", scope)).toBe(true);
    expect(await provider.search("identifier", scope)).toEqual([]);
  });
});
