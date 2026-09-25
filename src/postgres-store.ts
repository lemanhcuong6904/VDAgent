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
import type { ToolScope } from "./tool-pool.js";

const MAX_AGENT_MEMORY_BYTES = 1_000_000;
const MAX_PI_SESSION_BYTES = 4_000_000;

export class PostgresAgentMemoryProvider implements AgentMemoryProvider {
  constructor(private readonly pool: Pool) {}

  async remember(
    input: { key?: string; text: string; tags?: string[] },
    scope: ToolScope,
  ): Promise<void> {
    const identity = memoryIdentity(scope);
    const bytes = Buffer.byteLength(input.text);
    const key =
      input.key?.trim() || `sha256:${createHash("sha256").update(input.text).digest("hex")}`;
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [identity.key]);
      const current = await client.query<{ bytes: string; previous_bytes: string }>(
        `SELECT COALESCE(SUM(octet_length(text)), 0)::text AS bytes,
           COALESCE(SUM(octet_length(text)) FILTER (WHERE memory_key = $4), 0)::text AS previous_bytes
         FROM agent_memory_entries
         WHERE space_id = $1 AND user_id = $2 AND agent_id = $3`,
        [identity.spaceId, identity.userId, identity.agentId, key],
      );
      const usedBytes = Number(current.rows[0]?.bytes ?? 0);
      const previousBytes = Number(current.rows[0]?.previous_bytes ?? 0);
      if (usedBytes - previousBytes + bytes > MAX_AGENT_MEMORY_BYTES) {
        throw new Error("Agent memory is full");
      }
      await client.query(
        `INSERT INTO agent_memory_entries (id, space_id, user_id, agent_id, memory_key, text, tags)
         VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
         ON CONFLICT (space_id, user_id, agent_id, memory_key) DO UPDATE
         SET text = EXCLUDED.text, tags = EXCLUDED.tags, updated_at = now()`,
        [
          randomUUID(),
          identity.spaceId,
          identity.userId,
          identity.agentId,
          key,
          input.text,
          JSON.stringify(input.tags ?? []),
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
       WHERE id = $1 AND space_id = $2 AND user_id = $3 AND agent_id = $4`,
      [id, identity.spaceId, identity.userId, identity.agentId],
    );
    return result.rowCount === 1;
  }
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
      return new PostgresPiSessionLease(client, scope, lockKey);
    } catch (error) {
      client.release();
      throw error;
    }
  }
}

class PostgresPiSessionLease implements PiSessionLease {
  private released = false;

  constructor(
    private readonly client: PoolClient,
    private readonly scope: PiSessionScope,
    private readonly lockKey: string,
  ) {}

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
      await this.client.query("SELECT pg_advisory_unlock(hashtextextended($1, 0))", [this.lockKey]);
    } finally {
      this.client.release();
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
