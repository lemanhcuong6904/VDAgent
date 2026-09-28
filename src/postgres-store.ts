import { createHash, randomUUID } from "node:crypto";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { Pool, PoolClient } from "pg";
import type { AgentMemoryProvider } from "./memory-store.js";
import type {
  PiSessionLease,
  PiSessionScope,
  PiSessionSnapshot,
  PiSessionStore,
} from "./pi-session-store.js";
import type { AuditEntry, MemoryAuditWriter } from "./session/memory-provider.js";
import type { ToolScope } from "./tool-pool.js";

const MAX_AGENT_MEMORY_BYTES = 1_000_000;
const MAX_PI_SESSION_BYTES = 4_000_000;

/** Durable memory mutation audit journal. Retention is enforced at write time and on demand. */
export class PostgresMemoryAuditWriter implements MemoryAuditWriter {
  constructor(
    private readonly pool: Pool,
    private readonly options: { retentionDays?: number } = {},
  ) {}

  async recordAudit(entry: Omit<AuditEntry, "id" | "timestamp">): Promise<AuditEntry> {
    const id = `memory-audit-${Date.now().toString(36)}-${randomUUID()}`;
    const timestamp = new Date();
    const retentionDays = positiveRetentionDays(this.options.retentionDays);
    const expiresAt = new Date(timestamp.getTime() + retentionDays * 86_400_000);
    const audit: AuditEntry = {
      ...entry,
      id,
      timestamp: timestamp.toISOString(),
      actor: entry.actor.slice(0, 256),
      resource: entry.resource.slice(0, 256),
      details: redactMemoryAuditDetails(entry.details),
      reason: entry.reason?.slice(0, 512),
    };
    await this.pool.query(
      `INSERT INTO memory_audit_events
       (id, workspace_id, operation, actor, resource, details, success, reason, created_at, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)`,
      [
        audit.id,
        audit.workspaceId,
        audit.operation,
        audit.actor,
        audit.resource,
        JSON.stringify(audit.details ?? {}),
        audit.success,
        audit.reason ?? null,
        timestamp,
        expiresAt,
      ],
    );
    // Keep expired records out of normal reads even if the scheduled purge is delayed.
    await this.purgeExpired(500).catch(() => undefined);
    return audit;
  }

  async queryAudit(
    workspaceId: string,
    options: {
      operation?: AuditEntry["operation"];
      actor?: string;
      resource?: string;
      startTime?: string;
      endTime?: string;
      limit?: number;
    } = {},
  ): Promise<AuditEntry[]> {
    await this.purgeExpired(500).catch(() => undefined);
    const values: unknown[] = [workspaceId];
    const predicates = ["workspace_id = $1", "expires_at > now()"];
    if (options.operation) {
      values.push(options.operation);
      predicates.push(`operation = $${values.length}`);
    }
    if (options.actor) {
      values.push(options.actor);
      predicates.push(`actor = $${values.length}`);
    }
    if (options.resource) {
      values.push(options.resource);
      predicates.push(`resource = $${values.length}`);
    }
    if (options.startTime) {
      values.push(options.startTime);
      predicates.push(`created_at >= $${values.length}`);
    }
    if (options.endTime) {
      values.push(options.endTime);
      predicates.push(`created_at <= $${values.length}`);
    }
    const limit = Math.min(Math.max(options.limit ?? 100, 1), 1000);
    values.push(limit);
    const result = await this.pool.query<{
      id: string;
      workspace_id: string;
      operation: AuditEntry["operation"];
      actor: string;
      resource: string;
      details: Record<string, unknown>;
      success: boolean;
      reason: string | null;
      created_at: Date;
    }>(
      `SELECT id, workspace_id, operation, actor, resource, details, success, reason, created_at
       FROM memory_audit_events WHERE ${predicates.join(" AND ")}
       ORDER BY created_at DESC, id DESC LIMIT $${values.length}`,
      values,
    );
    return result.rows.map((row) => ({
      id: row.id,
      timestamp: row.created_at.toISOString(),
      workspaceId: row.workspace_id,
      operation: row.operation,
      actor: row.actor,
      resource: row.resource,
      details: row.details,
      success: row.success,
      reason: row.reason ?? undefined,
    }));
  }

  async purgeExpired(limit = 10_000): Promise<number> {
    const bounded = boundedPurgeLimit(limit, 10_000);
    const result = await this.pool.query(
      `DELETE FROM memory_audit_events
       WHERE id IN (
         SELECT id FROM memory_audit_events
         WHERE expires_at <= now()
         ORDER BY expires_at ASC
         LIMIT $1
       )`,
      [bounded],
    );
    return result.rowCount ?? 0;
  }
}

function positiveRetentionDays(value: number | undefined): number {
  return Number.isFinite(value) && (value as number) > 0 ? Math.min(value as number, 3650) : 365;
}

function redactMemoryAuditDetails(details: Record<string, unknown> | undefined) {
  if (!details) return undefined;
  const redact = (value: unknown, key: string, depth: number): unknown => {
    if (/(content|memory|secret|token|password|prompt)/i.test(key)) return "[redacted]";
    if (typeof value === "string") return value.slice(0, 512);
    if (Array.isArray(value)) return value.slice(0, 100).map((item) => redact(item, "", depth + 1));
    if (value && typeof value === "object") {
      if (depth >= 4) return "[truncated]";
      return Object.fromEntries(
        Object.entries(value)
          .slice(0, 100)
          .map(([childKey, childValue]) => [
            childKey.slice(0, 128),
            redact(childValue, childKey, depth + 1),
          ]),
      );
    }
    return value;
  };
  return redact(details, "", 0) as Record<string, unknown>;
}

export class PostgresAgentMemoryProvider implements AgentMemoryProvider {
  constructor(private readonly pool: Pool) {}

  async remember(
    input: { key?: string; text: string; tags?: string[] },
    scope: ToolScope,
  ): Promise<void> {
    const identity = memoryIdentity(scope);
    await this.purgeExpired(100);
    const bytes = Buffer.byteLength(input.text);
    const requestedExpiry = getExpiryFromTags(input.tags ?? []);
    const retentionDays = configuredMemoryRetentionDays();
    const maximumExpiry = Date.now() + retentionDays * 86_400_000;
    const requestedExpiryMs =
      requestedExpiry === null ? maximumExpiry : Date.parse(requestedExpiry);
    if (!Number.isFinite(requestedExpiryMs) || requestedExpiryMs <= Date.now())
      throw new Error("Agent memory expiration timestamp is invalid");
    const expiresAt = new Date(Math.min(requestedExpiryMs, maximumExpiry)).toISOString();
    const key =
      input.key?.trim() || `sha256:${createHash("sha256").update(input.text).digest("hex")}`;
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [identity.key]);
      const current = await client.query<{ bytes: string; previous_bytes: string }>(
        `SELECT COALESCE(SUM(octet_length(text)) FILTER (
             WHERE COALESCE(expires_at, updated_at + interval '365 days') > now()
           ), 0)::text AS bytes,
           COALESCE(SUM(octet_length(text)) FILTER (
             WHERE memory_key = $4
               AND COALESCE(expires_at, updated_at + interval '365 days') > now()
           ), 0)::text AS previous_bytes
         FROM agent_memory_entries
         WHERE space_id = $1 AND user_id = $2 AND agent_id = $3
           AND (expires_at IS NULL OR expires_at > now())`,
        [identity.spaceId, identity.userId, identity.agentId, key],
      );
      const usedBytes = Number(current.rows[0]?.bytes ?? 0);
      const previousBytes = Number(current.rows[0]?.previous_bytes ?? 0);
      if (usedBytes - previousBytes + bytes > MAX_AGENT_MEMORY_BYTES) {
        throw new Error("Agent memory is full");
      }
      await client.query(
        `INSERT INTO agent_memory_entries (id, space_id, user_id, agent_id, memory_key, text, tags, expires_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
         ON CONFLICT (space_id, user_id, agent_id, memory_key) DO UPDATE
         SET text = EXCLUDED.text, tags = EXCLUDED.tags, expires_at = EXCLUDED.expires_at, updated_at = now()`,
        [
          randomUUID(),
          identity.spaceId,
          identity.userId,
          identity.agentId,
          key,
          input.text,
          JSON.stringify(input.tags ?? []),
          expiresAt,
        ],
      );
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async search(
    query: string,
    scope: ToolScope,
  ): Promise<Array<{ id: string; key: string | null; text: string; tags: string[] }>> {
    const identity = memoryIdentity(scope);
    const result = await this.pool.query<{
      id: string;
      memory_key: string | null;
      text: string;
      tags: unknown;
    }>(
      `SELECT id, memory_key, text, tags FROM agent_memory_entries
       WHERE space_id = $1 AND user_id = $2 AND agent_id = $3
         AND COALESCE(expires_at, updated_at + interval '365 days') > now()
         AND to_tsvector('simple', text || ' ' || tags::text)
           @@ plainto_tsquery('simple', $4)
       ORDER BY ts_rank(to_tsvector('simple', text || ' ' || tags::text),
           plainto_tsquery('simple', $4)) DESC, updated_at DESC, id DESC LIMIT 8`,
      [identity.spaceId, identity.userId, identity.agentId, query.trim()],
    );
    return result.rows.map((row) => ({
      id: row.id,
      key: row.memory_key,
      text: row.text,
      tags: Array.isArray(row.tags)
        ? row.tags.filter((tag): tag is string => typeof tag === "string")
        : [],
    }));
  }

  async forget(id: string, scope: ToolScope): Promise<boolean> {
    const identity = memoryIdentity(scope);
    const result = await this.pool.query(
      `DELETE FROM agent_memory_entries
       WHERE id = (
         SELECT id FROM agent_memory_entries
         WHERE (memory_key = $1 OR id = $1)
           AND space_id = $2 AND user_id = $3 AND agent_id = $4
         ORDER BY CASE WHEN memory_key = $1 THEN 0 ELSE 1 END
         LIMIT 1
       )
         AND space_id = $2 AND user_id = $3 AND agent_id = $4`,
      [id, identity.spaceId, identity.userId, identity.agentId],
    );
    return result.rowCount === 1;
  }

  /** Remove at most `limit` expired notes; searches also exclude them before this purge runs. */
  async purgeExpired(limit = 1000): Promise<number> {
    const bounded = boundedPurgeLimit(limit, 1000);
    // Upgrade legacy unbounded notes incrementally instead of locking the entire memory table.
    await this.pool.query(
      `WITH batch AS (
         SELECT id FROM agent_memory_entries
         WHERE expires_at IS NULL
         ORDER BY updated_at ASC, id ASC
         LIMIT $1
         FOR UPDATE SKIP LOCKED
       )
       UPDATE agent_memory_entries AS memory
       SET expires_at = memory.updated_at + interval '365 days'
       FROM batch
       WHERE memory.id = batch.id`,
      [bounded],
    );
    const result = await this.pool.query(
      `DELETE FROM agent_memory_entries
       WHERE id IN (
         SELECT id FROM agent_memory_entries
         WHERE COALESCE(expires_at, updated_at + interval '365 days') <= now()
         ORDER BY expires_at ASC
         LIMIT $1
       )`,
      [bounded],
    );
    return result.rowCount ?? 0;
  }
}

/** Keep purge batch sizes valid for PostgreSQL LIMIT even when callers pass bad numbers. */
function boundedPurgeLimit(value: number, fallback: number): number {
  if (!Number.isFinite(value) || !Number.isInteger(value) || value <= 0) return fallback;
  return Math.min(value, 10_000);
}

function getExpiryFromTags(tags: readonly string[]): string | null {
  return tags.find((tag) => tag.startsWith("expiresAt:"))?.slice("expiresAt:".length) ?? null;
}

function configuredMemoryRetentionDays(): number {
  const value = Number(process.env.MEMORY_RETENTION_DAYS ?? 365);
  const days = Math.floor(value);
  return Number.isFinite(days) && days >= 1 ? Math.min(days, 3650) : 365;
}

export class PostgresPiSessionStore implements PiSessionStore {
  constructor(private readonly pool: Pool) {}

  async open(scope: PiSessionScope) {
    assertSessionScope(scope);
    const client = await this.pool.connect();
    const lockKey = JSON.stringify([scope.spaceId, scope.userId, scope.agentId, scope.sessionId]);
    try {
      const lock = await client.query<{ locked: boolean }>(
        "SELECT pg_try_advisory_lock(hashtextextended($1, 0)) AS locked",
        [lockKey],
      );
      if (lock.rows[0]?.locked !== true) throw new PiSessionBusyError();
      const lease = new PostgresPiSessionLease(client, scope, lockKey);
      lease.attachConnectionErrorHandler();
      return lease;
    } catch (error) {
      client.release();
      throw error;
    }
  }
}

class PostgresPiSessionLease implements PiSessionLease {
  private released = false;
  private connectionError: Error | undefined;

  constructor(
    private readonly client: PoolClient,
    private readonly scope: PiSessionScope,
    private readonly lockKey: string,
  ) {}

  attachConnectionErrorHandler() {
    this.client.on("error", (error: Error) => {
      this.connectionError = error;
    });
  }

  async load(): Promise<PiSessionSnapshot> {
    this.assertOpen();
    const result = await this.client.query<{ messages: unknown; revision: number }>(
      `SELECT messages, revision FROM pi_sessions
       WHERE space_id = $1 AND user_id = $2 AND agent_id = $3 AND session_id = $4`,
      [this.scope.spaceId, this.scope.userId, this.scope.agentId, this.scope.sessionId],
    );
    const row = result.rows[0];
    if (!row) return { messages: [], revision: 0 };
    if (!Array.isArray(row.messages)) throw new Error("Pi session data is invalid");
    return { messages: row.messages as AgentMessage[], revision: row.revision };
  }

  async save(messages: AgentMessage[], expectedRevision: number): Promise<number> {
    this.assertOpen();
    const encoded = JSON.stringify(messages);
    if (Buffer.byteLength(encoded) > MAX_PI_SESSION_BYTES) {
      throw new Error("Pi session exceeds the byte limit");
    }
    const values = [
      this.scope.spaceId,
      this.scope.userId,
      this.scope.agentId,
      this.scope.sessionId,
      encoded,
    ];
    const result =
      expectedRevision === 0
        ? await this.client.query<{ revision: number }>(
            `INSERT INTO pi_sessions
               (space_id, user_id, agent_id, session_id, messages, revision, updated_at)
             VALUES ($1, $2, $3, $4, $5::jsonb, 1, now())
             ON CONFLICT DO NOTHING
             RETURNING revision`,
            values,
          )
        : await this.client.query<{ revision: number }>(
            `UPDATE pi_sessions SET messages = $5::jsonb, revision = revision + 1, updated_at = now()
             WHERE space_id = $1 AND user_id = $2 AND agent_id = $3 AND session_id = $4
               AND revision = $6
             RETURNING revision`,
            [...values, expectedRevision],
          );
    const revision = result.rows[0]?.revision;
    if (revision === undefined) throw new PiSessionConflictError();
    return revision;
  }

  async release(): Promise<void> {
    if (this.released) return;
    this.released = true;
    try {
      if (!this.connectionError) {
        await this.client.query("SELECT pg_advisory_unlock(hashtextextended($1, 0))", [
          this.lockKey,
        ]);
      }
    } finally {
      this.client.release(this.connectionError);
    }
  }

  private assertOpen() {
    if (this.released) throw new Error("Pi session lease is closed");
  }
}

export class PiSessionBusyError extends Error {
  constructor() {
    super("Pi session already has an active run");
    this.name = "PiSessionBusyError";
  }
}

export class PiSessionConflictError extends Error {
  constructor() {
    super("Pi session changed during the run; retry with the latest session state");
    this.name = "PiSessionConflictError";
  }
}

function memoryIdentity(scope: ToolScope) {
  if (!scope.agentId) throw new Error("Agent memory requires an agent identity");
  if (!scope.spaceId || !scope.userId)
    throw new Error("Agent memory requires a user and space scope");
  return {
    spaceId: scope.spaceId,
    userId: scope.userId,
    agentId: scope.agentId,
    key: JSON.stringify([scope.spaceId, scope.userId, scope.agentId]),
  };
}

function assertSessionScope(scope: PiSessionScope) {
  if (!scope.userId || !scope.spaceId || !scope.agentId || !scope.sessionId) {
    throw new Error("Pi session requires user, space, agent, and session identities");
  }
}
