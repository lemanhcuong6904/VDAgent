import { randomUUID } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import { assertRunTransition, type RunStatus } from "./run-state.js";

export interface CreateRunInput {
  id?: string;
  spaceId: string;
  userId: string;
  workflowId: string;
  workflowVersion: string;
  input: unknown;
  idempotencyKey: string;
  deadlineAt?: Date;
}

export interface CreatedRun {
  id: string;
  status: RunStatus;
  attempt: number;
  fencing_token: string;
  created_at: Date;
}

export interface ClaimedRun {
  id: string;
  space_id: string;
  user_id: string;
  workflow_id: string;
  workflow_version: string;
  status: RunStatus;
  input: unknown;
  attempt: number;
  fencing_token: string;
  lease_until: Date;
  deadline_at: Date | null;
  cancel_requested: boolean;
  max_attempts: number;
}

export interface RunEvent {
  run_id: string;
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: Date;
}

export class RunLedger {
  constructor(private readonly pool: Pool) {}

  async create(input: CreateRunInput): Promise<CreatedRun> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const created = await this.createOnClient(client, input);
      await client.query("COMMIT");
      return created;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  /** Create a run in the caller's transaction so task and queue state commit together. */
  async createOnClient(client: PoolClient, input: CreateRunInput): Promise<CreatedRun> {
    if (!input.idempotencyKey || input.idempotencyKey.length > 256) {
      throw new Error("idempotencyKey must contain 1-256 characters");
    }
    const id = input.id ?? `run_${randomUUID().replaceAll("-", "").slice(0, 16)}`;
    const result = await client.query<CreatedRun>(
      `INSERT INTO platform_runs
       (id, space_id, user_id, workflow_id, workflow_version, status, input, idempotency_key, deadline_at)
       VALUES ($1, $2, $3, $4, $5, 'queued', $6::jsonb, $7, $8)
       ON CONFLICT (space_id, user_id, idempotency_key)
       DO UPDATE SET updated_at = platform_runs.updated_at
       RETURNING id, status, attempt, fencing_token, created_at`,
      [
        id,
        input.spaceId,
        input.userId,
        input.workflowId,
        input.workflowVersion,
        encodeJson(input.input),
        input.idempotencyKey,
        input.deadlineAt ?? null,
      ],
    );
    const created = result.rows[0];
    if (!created) throw new Error("Run insert returned no row");
    await client.query(
      `INSERT INTO platform_idempotency_keys
       (space_id, user_id, idempotency_key, run_id)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (space_id, user_id, idempotency_key)
       DO NOTHING`,
      [input.spaceId, input.userId, input.idempotencyKey, created.id],
    );
    const queuedEvent = await client.query(
      "SELECT 1 FROM platform_run_events WHERE run_id = $1 AND event_type = 'run.queued' LIMIT 1",
      [created.id],
    );
    if (!queuedEvent.rowCount) {
      await this.appendEventOnClient(client, {
        runId: created.id,
        spaceId: input.spaceId,
        userId: input.userId,
        eventType: "run.queued",
        payload: { workflow_id: input.workflowId, workflow_version: input.workflowVersion },
      });
    }
    return created;
  }

  async claim(workerId: string, leaseMs = 30_000): Promise<ClaimedRun | undefined> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query<ClaimedRun>(
        `SELECT * FROM platform_runs
         WHERE (
           status IN ('queued', 'retryable')
           OR (status IN ('leased', 'running', 'waiting') AND lease_until < now())
         )
         AND cancel_requested = false
         AND (deadline_at IS NULL OR deadline_at > now())
         ORDER BY created_at
         FOR UPDATE SKIP LOCKED LIMIT 1`,
      );
      const run = result.rows[0];
      if (!run) {
        await client.query("COMMIT");
        return undefined;
      }
      const updated = await client.query<ClaimedRun>(
        `UPDATE platform_runs
         SET status = 'leased', worker_id = $2, lease_until = now() + ($3 * interval '1 millisecond'),
             attempt = attempt + 1, fencing_token = fencing_token + 1, updated_at = now()
         WHERE id = $1
         RETURNING *`,
        [run.id, workerId, leaseMs],
      );
      const claimed = updated.rows[0];
      if (!claimed) throw new Error(`Run '${run.id}' disappeared while claiming`);
      await client.query(
        `INSERT INTO platform_worker_leases (run_id, worker_id, fencing_token, lease_until)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (run_id) DO UPDATE SET worker_id = EXCLUDED.worker_id,
           fencing_token = EXCLUDED.fencing_token, lease_until = EXCLUDED.lease_until,
           heartbeat_at = now()`,
        [claimed.id, workerId, claimed.fencing_token, claimed.lease_until],
      );
      await this.appendEventOnClient(client, {
        runId: claimed.id,
        spaceId: claimed.space_id,
        userId: claimed.user_id,
        eventType: "run.leased",
        payload: { worker_id: workerId, attempt: claimed.attempt },
      });
      await client.query("COMMIT");
      return claimed;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async heartbeat(
    runId: string,
    workerId: string,
    fencingToken: string,
    leaseMs = 30_000,
  ): Promise<boolean> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query(
        `UPDATE platform_runs
         SET lease_until = now() + ($4 * interval '1 millisecond'), updated_at = now()
         WHERE id = $1 AND worker_id = $2 AND fencing_token = $3
           AND cancel_requested = false
           AND status IN ('leased', 'running', 'waiting')
         RETURNING id`,
        [runId, workerId, fencingToken, leaseMs],
      );
      if (!result.rowCount) {
        await client.query("ROLLBACK");
        return false;
      }
      await client.query(
        `UPDATE platform_worker_leases
         SET lease_until = now() + ($4 * interval '1 millisecond'), heartbeat_at = now()
         WHERE run_id = $1 AND worker_id = $2 AND fencing_token = $3`,
        [runId, workerId, fencingToken, leaseMs],
      );
      await client.query("COMMIT");
      return true;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async isCancellationRequested(
    runId: string,
    workerId: string,
    fencingToken: string,
  ): Promise<boolean> {
    const result = await this.pool.query<{ cancel_requested: boolean }>(
      `SELECT cancel_requested FROM platform_runs
       WHERE id = $1 AND worker_id = $2 AND fencing_token = $3`,
      [runId, workerId, fencingToken],
    );
    return Boolean(result.rows[0]?.cancel_requested);
  }

  async transition(
    runId: string,
    workerId: string,
    fencingToken: string,
    from: RunStatus,
    to: RunStatus,
    detail?: { output?: unknown; error?: string },
  ): Promise<boolean> {
    assertRunTransition(from, to);
    const terminal = to === "completed" || to === "failed" || to === "cancelled";
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query<{
        id: string;
        space_id: string;
        user_id: string;
        attempt: number;
      }>(
        `UPDATE platform_runs SET status = $5, output = COALESCE($6::jsonb, output),
           error = COALESCE($7, error), updated_at = now(),
           finished_at = CASE WHEN $8 THEN now() ELSE finished_at END
         WHERE id = $1 AND worker_id = $2 AND fencing_token = $3 AND status = $4
         RETURNING id, space_id, user_id, attempt`,
        [
          runId,
          workerId,
          fencingToken,
          from,
          to,
          detail?.output === undefined ? null : encodeJson(detail.output),
          detail?.error ?? null,
          terminal,
        ],
      );
      const row = result.rows[0];
      if (!row) {
        await client.query("ROLLBACK");
        return false;
      }
      await this.appendEventOnClient(client, {
        runId,
        spaceId: row.space_id,
        userId: row.user_id,
        eventType: "run.status",
        payload: {
          from,
          to,
          attempt: row.attempt,
          error: detail?.error,
          has_output: detail?.output !== undefined,
        },
      });
      await client.query("COMMIT");
      return true;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async cancel(runId: string, spaceId: string, userId: string): Promise<boolean> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query<{ id: string }>(
        `UPDATE platform_runs
         SET status = CASE WHEN status IN ('queued', 'retryable') THEN 'cancelled' ELSE status END,
             cancel_requested = true,
             finished_at = CASE WHEN status IN ('queued', 'retryable') THEN now() ELSE finished_at END,
             updated_at = now()
         WHERE id = $1 AND space_id = $2 AND user_id = $3
           AND status IN ('queued', 'retryable', 'leased', 'running', 'waiting')
         RETURNING id`,
        [runId, spaceId, userId],
      );
      if (!result.rowCount) {
        await client.query("ROLLBACK");
        return false;
      }
      await this.appendEventOnClient(client, {
        runId,
        spaceId,
        userId,
        eventType: "run.cancel_requested",
        payload: { run_id: runId },
      });
      await client.query("COMMIT");
      return true;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async eventsAfter(runId: string, afterSeq = 0, limit = 100): Promise<RunEvent[]> {
    const boundedLimit = Math.min(1000, Math.max(1, Math.floor(limit)));
    const result = await this.pool.query<RunEvent>(
      `SELECT run_id, seq, event_type, payload, created_at
       FROM platform_run_events
       WHERE run_id = $1 AND seq > $2
       ORDER BY seq ASC LIMIT $3`,
      [runId, Math.max(0, Math.floor(afterSeq)), boundedLimit],
    );
    return result.rows;
  }

  private async appendEventOnClient(
    client: PoolClient,
    input: {
      runId: string;
      spaceId: string;
      userId: string;
      eventType: string;
      payload: unknown;
    },
  ): Promise<number> {
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [input.runId]);
    const seq = await client.query<{ seq: string }>(
      "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM platform_run_events WHERE run_id = $1",
      [input.runId],
    );
    const next = Number(seq.rows[0]?.seq ?? 1);
    const payload = eventPayload(input.payload, next);
    await client.query(
      `INSERT INTO platform_run_events (run_id, space_id, user_id, seq, event_type, payload)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
      [input.runId, input.spaceId, input.userId, next, input.eventType, encodeJson(payload)],
    );
    await client.query(
      `INSERT INTO platform_outbox_events (run_id, event_type, payload)
       VALUES ($1, $2, $3::jsonb)`,
      [input.runId, input.eventType, encodeJson(payload)],
    );
    return next;
  }

  async appendEvent(input: {
    runId: string;
    spaceId: string;
    userId: string;
    eventType: string;
    payload: unknown;
  }): Promise<number> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const seq = await this.appendEventOnClient(client, input);
      await client.query("COMMIT");
      return seq;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }
}

function encodeJson(value: unknown): string {
  const encoded = JSON.stringify(value ?? null);
  if (encoded === undefined) throw new Error("Run payload must be JSON serializable");
  return encoded;
}

function eventPayload(value: unknown, seq: number): Record<string, unknown> {
  if (isRecord(value)) return { ...value, seq };
  return { value: value ?? null, seq };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
