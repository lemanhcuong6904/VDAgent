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

export class IdempotencyConflictError extends Error {
  constructor() {
    super("Idempotency key is already bound to a different run payload");
    this.name = "IdempotencyConflictError";
  }
}

export interface UsageRecordInput {
  runId?: string;
  userId: string;
  spaceId: string;
  kind: "model" | "tool" | "sandbox" | "worker";
  provider?: string;
  model?: string;
  agentId?: string;
  toolName?: string;
  inputTokens?: number;
  outputTokens?: number;
  latencyMs?: number;
  estimatedCost?: number;
  metadata?: Record<string, unknown>;
}

export class RunLedger {
  constructor(private readonly pool: Pool) {}

  async recordUsage(input: UsageRecordInput): Promise<void> {
    // Web tasks pass their invocation id as runId. Resolve it to the owning platform run so the
    // FK holds (an unresolved id used to fail the insert, and callers swallow that error).
    await this.pool.query(
      `WITH resolved AS (
         SELECT COALESCE(
           (SELECT id FROM platform_runs WHERE id = $1::text),
           (SELECT task.platform_run_id FROM web_invocations invocation
            JOIN web_tasks task ON task.id = invocation.task_id
            WHERE invocation.id = $1::text)
         ) AS run_id
       )
       INSERT INTO platform_usage_records
       (run_id, user_id, space_id, kind, provider, model, agent_id, tool_name,
        input_tokens, output_tokens, latency_ms, estimated_cost, metadata)
       SELECT resolved.run_id, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
         CASE WHEN $1::text IS NOT NULL AND resolved.run_id IS DISTINCT FROM $1::text
           THEN $13::jsonb || jsonb_build_object('source_run_id', $1::text)
           ELSE $13::jsonb END
       FROM resolved`,
      [
        input.runId ?? null,
        input.userId,
        input.spaceId,
        input.kind,
        input.provider ?? null,
        input.model ?? null,
        input.agentId ?? null,
        input.toolName ?? null,
        boundedInteger(input.inputTokens),
        boundedInteger(input.outputTokens),
        boundedInteger(input.latencyMs),
        input.estimatedCost ?? null,
        JSON.stringify(input.metadata ?? {}),
      ],
    );
  }

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
    const encodedInput = encodeJson(input.input);
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
        encodedInput,
        input.idempotencyKey,
        input.deadlineAt ?? null,
      ],
    );
    const created = result.rows[0];
    if (!created) throw new Error("Run insert returned no row");
    const existing = await client.query<{
      workflow_id: string;
      workflow_version: string;
      input: unknown;
    }>(
      `SELECT workflow_id, workflow_version, input
       FROM platform_runs WHERE id = $1 FOR UPDATE`,
      [created.id],
    );
    const stored = existing.rows[0];
    if (
      !stored ||
      stored.workflow_id !== input.workflowId ||
      stored.workflow_version !== input.workflowVersion ||
      !jsonbEqual(stored.input, input.input)
    ) {
      throw new IdempotencyConflictError();
    }
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
      await this.expireUnclaimableRunsOnClient(client);
      const result = await client.query<ClaimedRun>(
        `SELECT * FROM platform_runs
         WHERE (
           status IN ('queued', 'retryable')
           OR (status IN ('leased', 'running', 'waiting') AND lease_until < now())
         )
         AND cancel_requested = false
         AND (deadline_at IS NULL OR deadline_at > now())
         AND attempt < max_attempts
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
           AND (deadline_at IS NULL OR deadline_at > now())
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
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query<{
        id: string;
        space_id: string;
        user_id: string;
        attempt: number;
        status: RunStatus;
        error: string | null;
      }>(
        `UPDATE platform_runs SET status = CASE
             WHEN cancel_requested THEN 'cancelled'
             WHEN deadline_at IS NOT NULL AND deadline_at <= now() THEN 'failed'
             WHEN $5 = 'retryable' AND attempt >= max_attempts THEN 'failed'
             ELSE $5 END,
           output = CASE WHEN cancel_requested OR (deadline_at IS NOT NULL AND deadline_at <= now()) THEN output
                         ELSE COALESCE($6::jsonb, output) END,
           error = CASE
             WHEN cancel_requested THEN 'Run cancelled'
             WHEN deadline_at IS NOT NULL AND deadline_at <= now() THEN 'Run deadline exceeded'
             WHEN $5 = 'retryable' AND attempt >= max_attempts THEN 'Maximum attempts exceeded'
             WHEN $5 = 'running' THEN NULL
             ELSE COALESCE($7, error) END,
           updated_at = now(),
           finished_at = CASE
             WHEN cancel_requested OR (deadline_at IS NOT NULL AND deadline_at <= now())
               OR ($5 = 'retryable' AND attempt >= max_attempts)
               OR $5 IN ('completed', 'failed', 'cancelled')
             THEN now() ELSE finished_at END
         WHERE id = $1 AND worker_id = $2 AND fencing_token = $3 AND status = $4
         RETURNING id, space_id, user_id, attempt, status, error`,
        [
          runId,
          workerId,
          fencingToken,
          from,
          to,
          detail?.output === undefined ? null : encodeJson(detail.output),
          detail?.error ?? null,
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
          to: row.status,
          attempt: row.attempt,
          error: row.error ?? undefined,
          has_output: detail?.output !== undefined,
        },
      });
      if (row.status !== "leased" && row.status !== "running" && row.status !== "waiting") {
        await client.query("DELETE FROM platform_worker_leases WHERE run_id = $1", [runId]);
      }
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
      const current = await client.query<{ id: string; status: RunStatus; attempt: number }>(
        `SELECT id, status, attempt FROM platform_runs
         WHERE id = $1 AND space_id = $2 AND user_id = $3
           AND status IN ('queued', 'retryable', 'leased', 'running', 'waiting')
         FOR UPDATE`,
        [runId, spaceId, userId],
      );
      const previous = current.rows[0];
      if (!previous) {
        await client.query("ROLLBACK");
        return false;
      }
      const result = await client.query<{ id: string; status: RunStatus }>(
        `UPDATE platform_runs
         SET status = CASE WHEN status IN ('queued', 'retryable') THEN 'cancelled' ELSE status END,
             cancel_requested = true,
             error = CASE WHEN status IN ('queued', 'retryable') THEN 'Run cancelled' ELSE error END,
             finished_at = CASE WHEN status IN ('queued', 'retryable') THEN now() ELSE finished_at END,
             updated_at = now()
         WHERE id = $1 AND space_id = $2 AND user_id = $3
           AND status IN ('queued', 'retryable', 'leased', 'running', 'waiting')
         RETURNING id, status`,
        [runId, spaceId, userId],
      );
      const updated = result.rows[0];
      if (!updated) {
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
      if (updated.status === "cancelled") {
        await this.appendEventOnClient(client, {
          runId,
          spaceId,
          userId,
          eventType: "run.status",
          payload: {
            from: previous.status,
            to: "cancelled",
            attempt: previous.attempt,
            error: "Run cancelled",
          },
        });
        await client.query("DELETE FROM platform_worker_leases WHERE run_id = $1", [runId]);
      }
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

  private async expireUnclaimableRunsOnClient(client: PoolClient): Promise<void> {
    const expired = await client.query<{
      id: string;
      space_id: string;
      user_id: string;
      previous_status: RunStatus;
      status: RunStatus;
      attempt: number;
      reason: string;
    }>(
      `WITH candidates AS (
         SELECT id, status AS previous_status, space_id, user_id, attempt,
                cancel_requested, deadline_at, max_attempts
         FROM platform_runs
         WHERE status IN ('queued', 'retryable', 'leased', 'running', 'waiting')
           AND (
             (deadline_at IS NOT NULL AND deadline_at <= now())
             OR (attempt >= max_attempts AND (
               status IN ('queued', 'retryable')
               OR (status IN ('leased', 'running', 'waiting') AND lease_until < now())
             ))
             OR (cancel_requested AND (
               status IN ('queued', 'retryable') OR lease_until IS NULL OR lease_until < now()
             ))
           )
         FOR UPDATE SKIP LOCKED
       ), transitioned AS (
         UPDATE platform_runs AS run
         SET status = CASE
               WHEN candidate.cancel_requested THEN 'cancelled'
               WHEN candidate.deadline_at IS NOT NULL AND candidate.deadline_at <= now() THEN 'failed'
               ELSE 'failed' END,
             error = CASE
               WHEN candidate.cancel_requested THEN 'Run cancelled'
               WHEN candidate.deadline_at IS NOT NULL AND candidate.deadline_at <= now()
                 THEN 'Run deadline exceeded'
               ELSE 'Maximum attempts exceeded' END,
             finished_at = now(), updated_at = now()
         FROM candidates AS candidate
         WHERE run.id = candidate.id
         RETURNING run.id, run.space_id, run.user_id, run.status, run.attempt,
                   run.error, candidate.previous_status
       )
       SELECT id, space_id, user_id, previous_status, status, attempt, error AS reason
       FROM transitioned`,
    );
    for (const row of expired.rows) {
      await client.query("DELETE FROM platform_worker_leases WHERE run_id = $1", [row.id]);
      await this.appendEventOnClient(client, {
        runId: row.id,
        spaceId: row.space_id,
        userId: row.user_id,
        eventType: "run.status",
        payload: {
          from: row.previous_status,
          to: row.status,
          attempt: row.attempt,
          error: row.reason,
        },
      });
    }
  }
}

function encodeJson(value: unknown): string {
  const encoded = JSON.stringify(value ?? null);
  if (encoded === undefined) throw new Error("Run payload must be JSON serializable");
  return encoded;
}

function jsonbEqual(left: unknown, right: unknown): boolean {
  return stableJson(left) === stableJson(right);
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`)
    .join(",")}}`;
}

function eventPayload(value: unknown, seq: number): Record<string, unknown> {
  if (isRecord(value)) return { ...value, seq };
  return { value: value ?? null, seq };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedInteger(value: number | undefined): number | null {
  if (value === undefined) return null;
  if (!Number.isSafeInteger(value) || value < 0)
    throw new Error("Usage values must be non-negative integers");
  return value;
}
