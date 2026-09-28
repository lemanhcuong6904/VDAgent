/**
 * Versioned public API — M12.1
 *
 * Surface: /api/v1/{registry,activation,plan,run,step,checkpoint,memory,evidence}
 * Every route is scoped to the authenticated user and the caller's space; nothing
 * here widens authority beyond the ledger, which stays canonical.
 */

import { randomUUID } from "node:crypto";
import type { Context, Hono } from "hono";
import { streamSSE } from "hono/streaming";
import type { ContentfulStatusCode } from "hono/utils/http-status";
import type { Pool } from "pg";
import type { ArtifactMetadata } from "./artifact-storage.js";
import { ArtifactStorage } from "./artifact-storage.js";
import type { Evidence } from "./evidence-storage.js";
import { EvidenceStorage } from "./evidence-storage.js";
import { ObservatoryProjector } from "./observatory.js";
import type { AgentPool } from "./registry.js";
import { IdempotencyConflictError, type RunEvent, type RunLedger } from "./run-ledger.js";
import { isTerminalRunStatus } from "./run-state.js";
import { buildRunView } from "./run-view.js";
import { type TerminalReceipt, TerminalReceiptStorage } from "./terminal-receipt-storage.js";
import { bearerToken, verifyWebSession, type WebAuthConfig } from "./web-auth.js";
import type { PlanSpec } from "./workflow/workflow-module.js";

export const PLATFORM_API_PREFIX = "/api/v1";
export const DEFAULT_PAGE_LIMIT = 50;
export const MAX_PAGE_LIMIT = 200;

const IDENTIFIER = /^[a-zA-Z0-9._:-]{1,128}$/;

export type PlatformApiDependencies = {
  database: Pool;
  pluginRegistry: AgentPool;
  webAuth?: WebAuthConfig;
  runLedger?: RunLedger;
  /** Deployment workspace. Requests cannot switch to an arbitrary X-Space-Id. */
  spaceId?: string;
  /** Poll interval for the SSE run stream; tests shorten it. */
  streamPollMs?: number;
};

export type PlatformApiScope = { userId: string; spaceId: string };

/** Resolve the caller's identity and space, or undefined when unauthenticated. */
export async function resolvePlatformApiScope(
  context: Context,
  database: Pool,
  config?: WebAuthConfig,
  configuredSpaceId = process.env.API_SPACE_ID ?? "local-space",
): Promise<PlatformApiScope | undefined> {
  // Missing auth configuration must not silently turn the public API into demo mode.
  const authConfig = config ?? { mode: "session" as const, ttlSeconds: 0 };
  const session = verifyWebSession(bearerToken(context.req.header("authorization")), authConfig);
  const userId =
    session?.userId ??
    (authConfig.mode === "session" ? undefined : context.req.header("x-user-id"));
  if (!userId || !IDENTIFIER.test(userId)) return undefined;
  const result = await database.query("SELECT id FROM web_users WHERE id = $1", [userId]);
  if (!result.rows[0]) return undefined;

  const spaceId = configuredSpaceId.trim();
  const requested = context.req.header("x-space-id")?.trim();
  if (requested && requested !== spaceId) return undefined;
  if (!IDENTIFIER.test(spaceId)) return undefined;
  return { userId, spaceId };
}

export function registerPlatformApi(app: Hono, dependencies: PlatformApiDependencies): void {
  const { database, pluginRegistry, webAuth, runLedger } = dependencies;
  const spaceId = dependencies.spaceId ?? process.env.API_SPACE_ID ?? "local-space";
  const artifacts = new ArtifactStorage(database);
  const evidence = new EvidenceStorage(database, {
    requireArtifactVerification: true,
  });
  const receipts = new TerminalReceiptStorage(database);
  const observatory = new ObservatoryProjector(database);

  /** Every route runs inside the same scope gate; a handler never sees an unscoped id. */
  async function scoped(
    context: Context,
    handler: (scope: PlatformApiScope) => Promise<Response>,
  ): Promise<Response> {
    const scope = await resolvePlatformApiScope(context, database, webAuth, spaceId).catch(
      () => undefined,
    );
    if (!scope) {
      return error(context, 401, "authentication_required", "A valid web session is required");
    }
    try {
      return await handler(scope);
    } catch (failure) {
      if (failure instanceof IdempotencyConflictError) {
        return error(
          context,
          409,
          "idempotency_conflict",
          "This idempotency key was already used with a different request",
        );
      }
      const message = failure instanceof Error ? failure.message : "Request failed";
      return error(context, 500, "internal_error", message);
    }
  }

  // ---- Service metadata -------------------------------------------------

  app.get(`${PLATFORM_API_PREFIX}/meta`, (context) =>
    context.json({
      api_version: "v1",
      resources: [
        "registry",
        "activation",
        "plan",
        "run",
        "step",
        "checkpoint",
        "memory",
        "evidence",
        "view",
      ],
      limits: { default: DEFAULT_PAGE_LIMIT, max: MAX_PAGE_LIMIT },
      event_cursor: "seq",
    }),
  );

  // ---- Registry and activation ------------------------------------------

  app.get(`${PLATFORM_API_PREFIX}/registry/agents`, async (context) =>
    scoped(context, async () => context.json({ agents: pluginRegistry.list() })),
  );

  app.get(`${PLATFORM_API_PREFIX}/registry/agents/:agentId`, async (context) =>
    scoped(context, async (scope) => {
      const agentId = context.req.param("agentId");
      const plugin = pluginRegistry.get(agentId);
      if (!plugin) return error(context, 404, "not_found", "Unknown agent");
      return context.json({
        ...plugin.descriptor,
        // Kept identical to the legacy route so the adapter in M12.2 can compare payloads.
        space_id: scope.spaceId,
      });
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/activation/agents`, async (context) =>
    scoped(context, async () =>
      context.json({
        agents: pluginRegistry.list().map((agent) => ({
          agent_id: agent.id,
          version: agent.version,
          state: "enabled",
          canary_percentage: null,
          allowlist: [],
        })),
        note: "Activation state is process configuration; the durable registry is not yet migrated.",
      }),
    ),
  );

  app.post(`${PLATFORM_API_PREFIX}/activation/agents/:agentId/:version`, async (context) =>
    scoped(context, async () =>
      error(
        context,
        501,
        "not_supported",
        "Runtime activation mutation requires the durable agent registry and is not exposed here",
      ),
    ),
  );

  // ---- Plan --------------------------------------------------------------

  app.post(`${PLATFORM_API_PREFIX}/plan/validate`, async (context) =>
    scoped(context, async () => {
      const body = await readJson(context);
      if (body === MALFORMED) return error(context, 400, "invalid_json", "Body is not valid JSON");
      if (!isRecord(body) || !isRecord(body.plan)) {
        return error(context, 422, "invalid_plan", "Body must contain a plan object");
      }
      const { PlanValidator } = await import("./workflow/plan-validator.js");
      const capabilities = body.capabilities;
      const budget = isRecord(body.budget) ? (body.budget as never) : ({} as never);
      const result = new PlanValidator().validate(
        body.plan as unknown as PlanSpec,
        Array.isArray(capabilities) ? (capabilities as string[]) : [],
        budget,
      );
      return context.json({ valid: result.valid, errors: result.errors ?? [] });
    }),
  );

  // ---- Runs --------------------------------------------------------------

  app.get(`${PLATFORM_API_PREFIX}/runs`, async (context) =>
    scoped(context, async (scope) => {
      const limit = parseLimit(context.req.query("limit"));
      const status = context.req.query("status");
      const result = await database.query(
        `SELECT id, workflow_id, workflow_version, status, attempt, max_attempts,
                cancel_requested, created_at, updated_at, finished_at
         FROM platform_runs
         WHERE space_id = $1 AND user_id = $2 AND ($3::text IS NULL OR status = $3)
         ORDER BY created_at DESC LIMIT $4`,
        [scope.spaceId, scope.userId, status ?? null, limit],
      );
      return context.json({ runs: result.rows.map(toRunSummary), limit });
    }),
  );

  app.post(`${PLATFORM_API_PREFIX}/runs`, async (context) =>
    scoped(context, async (scope) => {
      if (!runLedger) return error(context, 503, "runner_disabled", "Run ledger is unavailable");
      const body = await readJson(context);
      if (body === MALFORMED) return error(context, 400, "invalid_json", "Body is not valid JSON");
      if (!isRecord(body) || typeof body.workflow_id !== "string") {
        return error(context, 422, "invalid_request", "workflow_id is required");
      }
      const idempotencyKey =
        context.req.header("idempotency-key") ??
        (typeof body.idempotency_key === "string" ? body.idempotency_key : undefined);
      if (!idempotencyKey || idempotencyKey.length > 256) {
        return error(
          context,
          422,
          "missing_idempotency_key",
          "An idempotency key of 1-256 characters is required",
        );
      }
      const workflowVersion =
        typeof body.workflow_version === "string" ? body.workflow_version : "1.0.0";
      const input = body.input ?? {};
      // Proposing our own id makes replay detection race-free: the ledger's
      // ON CONFLICT returns the earlier row, so a different id means a replay.
      const proposedId = `run_${randomUUID().replaceAll("-", "").slice(0, 16)}`;
      const created = await runLedger.create({
        id: proposedId,
        spaceId: scope.spaceId,
        userId: scope.userId,
        workflowId: body.workflow_id,
        workflowVersion,
        input,
        idempotencyKey,
        deadlineAt: typeof body.deadline_at === "string" ? new Date(body.deadline_at) : undefined,
      });
      if (created.id === proposedId) {
        return context.json({ run_id: created.id, status: created.status, replayed: false }, 202);
      }
      const original = await database.query<{
        workflow_id: string;
        workflow_version: string;
        input: unknown;
        status: string;
      }>(
        `SELECT workflow_id, workflow_version, input, status FROM platform_runs
         WHERE id = $1 AND space_id = $2 AND user_id = $3`,
        [created.id, scope.spaceId, scope.userId],
      );
      const row = original.rows[0];
      const requested = requestFingerprint(body.workflow_id, workflowVersion, input);
      if (
        row &&
        requestFingerprint(row.workflow_id, row.workflow_version, row.input) !== requested
      ) {
        return error(
          context,
          409,
          "idempotency_conflict",
          "This idempotency key was already used with a different request",
        );
      }
      return context.json({
        run_id: created.id,
        status: row?.status ?? created.status,
        replayed: true,
      });
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/runs/:runId`, async (context) =>
    scoped(context, async (scope) => {
      const run = await loadRun(database, context.req.param("runId"), scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      return context.json(toRunDetail(run));
    }),
  );

  app.post(`${PLATFORM_API_PREFIX}/runs/:runId/cancel`, async (context) =>
    scoped(context, async (scope) => {
      if (!runLedger) return error(context, 503, "runner_disabled", "Run ledger is unavailable");
      const cancelled = await runLedger.cancel(
        context.req.param("runId"),
        scope.spaceId,
        scope.userId,
      );
      if (!cancelled) {
        return error(context, 409, "not_cancellable", "Run is unknown or already terminal");
      }
      return context.json({ run_id: context.req.param("runId"), cancel_requested: true });
    }),
  );

  /** Cursor replay: `after` is the last sequence number the client already holds. */
  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/events`, async (context) =>
    scoped(context, async (scope) => {
      const runId = context.req.param("runId");
      const run = await loadRun(database, runId, scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      const after = parseCursor(context.req.query("after"));
      if (after === undefined) return error(context, 422, "invalid_cursor", "Invalid after cursor");
      const limit = parseLimit(context.req.query("limit"));
      const events = runLedger
        ? await runLedger.eventsAfter(runId, after, limit)
        : await loadEventsDirectly(database, runId, after, limit);
      const last = events.at(-1);
      return context.json({
        run_id: runId,
        events: events.map(toEventDto),
        cursor: last ? Number(last.seq) : after,
        has_more: events.length === limit,
      });
    }),
  );

  /**
   * Live stream of the same event log. Reconnect with `Last-Event-ID` (or `after`)
   * set to the last seq applied; the stream resumes from the durable log, so a
   * restart of this process loses nothing. Closes once the run is terminal and drained.
   */
  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/stream`, async (context) =>
    scoped(context, async (scope) => {
      const runId = context.req.param("runId");
      const run = await loadRun(database, runId, scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      let cursor = parseCursor(context.req.query("after") ?? context.req.header("last-event-id"));
      if (cursor === undefined)
        return error(context, 422, "invalid_cursor", "Invalid event cursor");
      const pollMs = dependencies.streamPollMs ?? 1_000;
      return streamSSE(context, async (stream) => {
        const signal = context.req.raw.signal;
        while (!signal.aborted) {
          const events = runLedger
            ? await runLedger.eventsAfter(runId, cursor as number, MAX_PAGE_LIMIT)
            : await loadEventsDirectly(database, runId, cursor as number, MAX_PAGE_LIMIT);
          for (const event of events) {
            const dto = toEventDto(event);
            await stream.writeSSE({
              id: String(dto.seq),
              event: dto.event_type,
              data: JSON.stringify(dto),
            });
            cursor = dto.seq;
          }
          if (events.length === MAX_PAGE_LIMIT) continue;
          const current = await loadRun(database, runId, scope);
          if (!current || isTerminalRunStatus(String(current.status) as never)) {
            // Events committed between the read above and the terminal status must still be sent.
            const tail = runLedger
              ? await runLedger.eventsAfter(runId, cursor as number, MAX_PAGE_LIMIT)
              : await loadEventsDirectly(database, runId, cursor as number, MAX_PAGE_LIMIT);
            if (tail.length) continue;
            await stream.writeSSE({
              event: "stream.end",
              data: JSON.stringify({ run_id: runId, cursor, status: current?.status ?? null }),
            });
            return;
          }
          await stream.sleep(pollMs);
        }
      });
    }),
  );

  // ---- Steps -------------------------------------------------------------

  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/steps`, async (context) =>
    scoped(context, async (scope) => {
      const run = await loadRun(database, context.req.param("runId"), scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      const result = await database.query(
        `SELECT id, parent_step_id, kind, agent_id, capability, status, attempt,
                created_at, started_at, finished_at,
                (input IS NOT NULL) AS has_input, (output IS NOT NULL) AS has_output
         FROM platform_run_steps WHERE run_id = $1 ORDER BY created_at ASC, id ASC`,
        [context.req.param("runId")],
      );
      return context.json({ steps: result.rows.map(toStepDto) });
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/steps/:stepId`, async (context) =>
    scoped(context, async (scope) => {
      const result = await database.query(
        `SELECT s.id, s.parent_step_id, s.kind, s.agent_id, s.capability, s.status,
                s.attempt, s.error, s.created_at, s.started_at, s.finished_at,
                (s.input IS NOT NULL) AS has_input, (s.output IS NOT NULL) AS has_output
         FROM platform_run_steps s
         JOIN platform_runs r ON r.id = s.run_id
         WHERE s.id = $1 AND r.space_id = $2 AND r.user_id = $3`,
        [context.req.param("stepId"), scope.spaceId, scope.userId],
      );
      const row = result.rows[0];
      if (!row) return error(context, 404, "not_found", "Step not found");
      return context.json(toStepDto(row));
    }),
  );

  // ---- Checkpoints -------------------------------------------------------

  /**
   * Checkpoints are projected from their evidence refs: the host records a
   * checkpoint evidence row (kind 'checkpoint') carrying id and revision, and the
   * byte-level manifest stays in agent storage. No state is read here.
   */
  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/checkpoints`, async (context) =>
    scoped(context, async (scope) => {
      const run = await loadRun(database, context.req.param("runId"), scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      const rows = await evidence.listByRun(context.req.param("runId"), scope.spaceId);
      const checkpoints = rows
        .filter((row) => row.kind === "checkpoint")
        .map((row) => {
          const checkpoint = row as Extract<Evidence, { kind: "checkpoint" }>;
          return {
            checkpoint_id: checkpoint.checkpointId,
            revision: checkpoint.checkpointRevision,
            evidence_id: checkpoint.id,
            verification: checkpoint.verification,
            created_at: checkpoint.createdAt.toISOString(),
          };
        });
      return context.json({ run_id: context.req.param("runId"), checkpoints });
    }),
  );

  // ---- Memory ------------------------------------------------------------

  /** Memory writes go through the agent tools; v1 exposes read-only inspection. */
  app.get(`${PLATFORM_API_PREFIX}/memory/:agentId`, async (context) =>
    scoped(context, async (scope) => {
      const agentId = context.req.param("agentId");
      const limit = parseLimit(context.req.query("limit"));
      const result = await database.query<{
        id: string;
        text: string;
        tags: unknown;
        created_at: Date;
      }>(
        `SELECT id, text, tags, created_at FROM agent_memory_entries
         WHERE space_id = $1 AND user_id = $2 AND agent_id = $3
         ORDER BY created_at DESC, id DESC LIMIT $4`,
        [scope.spaceId, scope.userId, agentId, limit],
      );
      return context.json({
        agent_id: agentId,
        entries: result.rows.map((row) => ({
          id: row.id,
          text: row.text,
          tags: Array.isArray(row.tags) ? row.tags : [],
          created_at: new Date(row.created_at).toISOString(),
        })),
        limit,
      });
    }),
  );

  // ---- Evidence, artifacts and receipts ----------------------------------

  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/evidence`, async (context) =>
    scoped(context, async (scope) => {
      const run = await loadRun(database, context.req.param("runId"), scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      const rows = await evidence.listByRun(context.req.param("runId"), scope.spaceId);
      return context.json({
        run_id: context.req.param("runId"),
        evidence: rows.map(toEvidenceDto),
      });
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/evidence/:evidenceId`, async (context) =>
    scoped(context, async (scope) => {
      const row = await evidence.get(context.req.param("evidenceId"), scope.spaceId, scope.userId);
      if (!row) return error(context, 404, "not_found", "Evidence not found");
      return context.json(toEvidenceDto(row));
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/artifacts/:artifactId`, async (context) =>
    scoped(context, async (scope) => {
      const artifactId = context.req.param("artifactId");
      if (!(await artifactBelongsToScope(database, artifactId, scope)))
        return error(context, 404, "not_found", "Artifact not found");
      const metadata = await artifacts.getMetadata(artifactId, scope.spaceId, scope.userId);
      if (!metadata) return error(context, 404, "not_found", "Artifact not found");
      return context.json(toArtifactDto(metadata));
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/artifacts/:artifactId/content`, async (context) =>
    scoped(context, async (scope) => {
      const artifactId = context.req.param("artifactId");
      if (!(await artifactBelongsToScope(database, artifactId, scope)))
        return error(context, 404, "not_found", "Artifact not found");
      const content = await artifacts.getContent(artifactId, scope.spaceId, scope.userId);
      if (!content) return error(context, 404, "not_found", "Artifact not found");
      // Artifact bytes are untrusted output. Never let a browser render them inline:
      // an HTML artifact served from this origin would run with the user's session.
      return context.body(new Uint8Array(content), 200, {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename="${context.req.param("artifactId").replace(/[^a-zA-Z0-9._-]/g, "_")}"`,
        "x-content-type-options": "nosniff",
        "content-security-policy": "sandbox; default-src 'none'",
        "cache-control": "private, no-store",
      });
    }),
  );

  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/receipt`, async (context) =>
    scoped(context, async (scope) => {
      const run = await loadRun(database, context.req.param("runId"), scope);
      if (!run) return error(context, 404, "not_found", "Run not found");
      const receipt = await receipts.getByRun(context.req.param("runId"), scope.spaceId);
      if (!receipt) {
        return error(context, 404, "receipt_missing", "No terminal receipt for this run");
      }
      return context.json(toReceiptDto(receipt));
    }),
  );

  // ---- Observatory projection (M11.5) ------------------------------------

  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/projection`, async (context) =>
    scoped(context, async (scope) => {
      const projection = await observatory.get(context.req.param("runId"), {
        spaceId: scope.spaceId,
        userId: scope.userId,
      });
      if (!projection) return error(context, 404, "not_found", "Run not found");
      return context.json(projection);
    }),
  );

  // ---- UI run view (M12.3) ------------------------------------------------

  /** Everything the run inspector renders, composed server-side behind one scope check. */
  app.get(`${PLATFORM_API_PREFIX}/runs/:runId/view`, async (context) =>
    scoped(context, async (scope) => {
      const runId = context.req.param("runId");
      const projection = await observatory.get(runId, {
        spaceId: scope.spaceId,
        userId: scope.userId,
      });
      if (!projection) return error(context, 404, "not_found", "Run not found");
      const run = await loadRun(database, runId, scope);
      const [rows, owned, receipt] = await Promise.all([
        evidence.listByRun(runId, scope.spaceId),
        artifacts.listByOwnerRun(runId),
        receipts.getByRun(runId, scope.spaceId),
      ]);
      return context.json(
        buildRunView({
          projection,
          cancelRequested: Boolean(run?.cancel_requested),
          evidence: rows,
          artifacts: owned,
          receipt,
          spaceId: scope.spaceId,
          apiPrefix: PLATFORM_API_PREFIX,
        }),
      );
    }),
  );

  // Must stay last: anything under the prefix that matched no route above gets the
  // v1 error envelope instead of the framework's plain-text 404.
  app.all(`${PLATFORM_API_PREFIX}/*`, (context) =>
    error(context, 404, "route_not_found", "No such v1 resource"),
  );
}

// ---- Row loaders ---------------------------------------------------------

async function loadRun(
  database: Pool,
  runId: string,
  scope: PlatformApiScope,
): Promise<Record<string, unknown> | undefined> {
  const result = await database.query(
    `SELECT id, space_id, user_id, workflow_id, workflow_version, status, error, attempt,
            max_attempts, cancel_requested, worker_id, lease_until, deadline_at,
            created_at, updated_at, finished_at
     FROM platform_runs WHERE id = $1 AND space_id = $2 AND user_id = $3`,
    [runId, scope.spaceId, scope.userId],
  );
  return result.rows[0];
}

async function loadEventsDirectly(
  database: Pool,
  runId: string,
  after: number,
  limit: number,
): Promise<RunEvent[]> {
  const result = await database.query<RunEvent>(
    `SELECT run_id, seq, event_type, payload, created_at FROM platform_run_events
     WHERE run_id = $1 AND seq > $2 ORDER BY seq ASC LIMIT $3`,
    [runId, after, limit],
  );
  return result.rows;
}

/** Check both current platform runs and legacy invocation ids before exposing an artifact. */
async function artifactBelongsToScope(
  database: Pool,
  artifactId: string,
  scope: PlatformApiScope,
): Promise<boolean> {
  const result = await database.query(
    `SELECT 1
     FROM artifacts a
     WHERE a.id = $1 AND a.workspace_id = $2
       AND (
         a.owner_user_id = $3
         OR EXISTS (
           SELECT 1 FROM platform_runs r
           WHERE r.id = a.owner_run_id AND r.space_id = $2 AND r.user_id = $3
         )
         OR EXISTS (
           SELECT 1
           FROM web_invocations i
           LEFT JOIN platform_runs r ON r.id = i.platform_run_id
           WHERE i.id = a.owner_run_id AND i.user_id = $3
             AND (r.id IS NULL OR (r.space_id = $2 AND r.user_id = $3))
         )
       )`,
    [artifactId, scope.spaceId, scope.userId],
  );
  return result.rows.length > 0;
}

// ---- DTOs ----------------------------------------------------------------

function toRunSummary(row: Record<string, unknown>) {
  return {
    run_id: row.id,
    workflow_id: row.workflow_id,
    workflow_version: row.workflow_version,
    status: row.status,
    attempt: Number(row.attempt ?? 0),
    cancel_requested: Boolean(row.cancel_requested),
    created_at: iso(row.created_at),
    updated_at: iso(row.updated_at),
    finished_at: row.finished_at ? iso(row.finished_at) : null,
  };
}

function toRunDetail(row: Record<string, unknown>) {
  const status = String(row.status);
  return {
    ...toRunSummary(row),
    error: row.error ?? null,
    max_attempts: Number(row.max_attempts ?? 1),
    terminal: isTerminalRunStatus(status as never),
    // Worker identity is operational detail; it is not part of the viewer contract.
    deadline_at: row.deadline_at ? iso(row.deadline_at) : null,
  };
}

function toStepDto(row: Record<string, unknown>) {
  return {
    step_id: row.id,
    parent_step_id: row.parent_step_id ?? null,
    kind: row.kind,
    agent_id: row.agent_id ?? null,
    capability: row.capability ?? null,
    status: row.status,
    attempt: Number(row.attempt ?? 0),
    error: row.error ?? null,
    // Step bodies are never serialized here; the projection and evidence carry what
    // a viewer may see. These flags let a client know a body exists.
    has_input: Boolean(row.has_input),
    has_output: Boolean(row.has_output),
    created_at: iso(row.created_at),
    started_at: row.started_at ? iso(row.started_at) : null,
    finished_at: row.finished_at ? iso(row.finished_at) : null,
  };
}

function toEventDto(event: RunEvent) {
  return {
    seq: Number(event.seq),
    event_type: event.event_type,
    payload: event.payload,
    created_at: iso(event.created_at),
  };
}

function toEvidenceDto(row: Evidence) {
  const base = {
    evidence_id: row.id,
    run_id: row.runId,
    attempt_id: row.attemptId,
    kind: row.kind,
    verification: row.verification,
    // `unavailable` is reported as-is; it is never upgraded to a success claim.
    unavailable: row.verification === "unavailable",
    created_at: row.createdAt.toISOString(),
    verified_at: row.verifiedAt ? row.verifiedAt.toISOString() : null,
  };
  switch (row.kind) {
    case "source":
      return {
        ...base,
        source_type: row.sourceType,
        source_location: row.sourceLocation,
        source_revision: row.sourceRevision,
      };
    case "tool_call":
      return {
        ...base,
        tool_id: row.toolId,
        tool_input_hash: row.toolInputHash,
        tool_output_hash: row.toolOutputHash,
      };
    case "model_call":
      return {
        ...base,
        model_id: row.modelId,
        model_input_hash: row.modelInputHash,
        model_output_hash: row.modelOutputHash,
        model_tokens: row.modelTokens,
      };
    case "artifact_ref":
      return { ...base, artifact_id: row.artifactId, artifact_sha256: row.artifactSha256 };
    case "checkpoint":
      return {
        ...base,
        checkpoint_id: row.checkpointId,
        checkpoint_revision: row.checkpointRevision,
      };
    default:
      return base;
  }
}

function toArtifactDto(row: ArtifactMetadata) {
  return {
    artifact_id: row.id,
    kind: row.kind,
    version: row.version,
    status: row.status,
    sha256: row.sha256 ?? null,
    bytes: row.bytes ?? null,
    owner_run_id: row.ownerRunId ?? null,
    created_at: iso(row.createdAt),
    ready_at: row.readyAt ? iso(row.readyAt) : null,
  };
}

function toReceiptDto(receipt: TerminalReceipt) {
  return {
    receipt_id: receipt.id,
    run_id: receipt.runId,
    attempt_id: receipt.attemptId,
    status: receipt.status,
    exit_code: receipt.exitCode,
    input_hash: receipt.inputHash,
    output_hash: receipt.outputHash,
    artifact_ids: receipt.artifactIds,
    evidence_count: Number(receipt.evidenceCount),
    verified_evidence_count: Number(receipt.verifiedEvidenceCount),
    duration_ms: receipt.durationMs === null ? null : Number(receipt.durationMs),
    tokens_input: receipt.tokensInput,
    tokens_output: receipt.tokensOutput,
    sealed_at: receipt.sealedAt.toISOString(),
  };
}

// ---- Small helpers -------------------------------------------------------

const MALFORMED = Symbol("malformed-json");

/** Distinguish "no/invalid JSON" (400) from "valid JSON, wrong shape" (422). */
async function readJson(context: Context): Promise<unknown> {
  const text = await context.req.text();
  if (text.trim() === "") return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return MALFORMED;
  }
}

/** Stable across key order so jsonb round-trips compare equal to the request. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

function requestFingerprint(workflowId: string, version: string, input: unknown): string {
  return canonicalJson({ workflow_id: workflowId, workflow_version: version, input });
}

function parseLimit(value: string | undefined): number {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) return DEFAULT_PAGE_LIMIT;
  return Math.min(parsed, MAX_PAGE_LIMIT);
}

function parseCursor(value: string | undefined): number | undefined {
  if (value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : undefined;
}

function iso(value: unknown): string {
  return new Date(value as string | Date).toISOString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function error(context: Context, status: number, code: string, message: string) {
  return context.json({ error: { code, message } }, status as ContentfulStatusCode);
}

// ---- Legacy adapter (M12.2) ----------------------------------------------

/** Legacy routes that have a v1 successor; responses are untouched, only headers are added. */
const LEGACY_SUCCESSORS: readonly [RegExp, string][] = [
  [/^\/api\/agents$/, `${PLATFORM_API_PREFIX}/registry/agents`],
  [/^\/api\/tasks\/[^/]+$/, `${PLATFORM_API_PREFIX}/runs`],
  [/^\/api\/tasks\/[^/]+\/cancel$/, `${PLATFORM_API_PREFIX}/runs`],
  [/^\/api\/events$/, `${PLATFORM_API_PREFIX}/runs`],
];

export function legacySuccessor(path: string): string | undefined {
  return LEGACY_SUCCESSORS.find(([pattern]) => pattern.test(path))?.[1];
}

/**
 * Register before `registerWebApi`. Old endpoints keep their exact bodies and status
 * codes; the adapter only advertises the successor so clients can migrate, and adds a
 * task→run bridge so a UI holding a legacy task id can switch to the v1 event cursor.
 */
export function registerLegacyAdapter(app: Hono, dependencies: PlatformApiDependencies): void {
  const { database, webAuth } = dependencies;

  app.use("/api/*", async (context, next) => {
    await next();
    if (context.req.path.startsWith(`${PLATFORM_API_PREFIX}/`)) return;
    const successor = legacySuccessor(context.req.path);
    if (!successor) return;
    context.header("Deprecation", "true");
    context.header("Link", `<${successor}>; rel="successor-version"`);
  });

  app.get(`${PLATFORM_API_PREFIX}/legacy/tasks/:taskId/run`, async (context) => {
    const scope = await resolvePlatformApiScope(
      context,
      database,
      webAuth,
      dependencies.spaceId ?? process.env.API_SPACE_ID ?? "local-space",
    ).catch(() => undefined);
    if (!scope)
      return error(context, 401, "authentication_required", "A valid web session is required");
    const result = await database.query<{ platform_run_id: string | null }>(
      "SELECT platform_run_id FROM web_tasks WHERE id = $1 AND user_id = $2",
      [context.req.param("taskId"), scope.userId],
    );
    const row = result.rows[0];
    if (!row) return error(context, 404, "not_found", "Task not found");
    if (!row.platform_run_id) {
      return error(context, 404, "run_missing", "Task predates the durable run ledger");
    }
    return context.json({
      task_id: context.req.param("taskId"),
      run_id: row.platform_run_id,
      events: `${PLATFORM_API_PREFIX}/runs/${row.platform_run_id}/events`,
      stream: `${PLATFORM_API_PREFIX}/runs/${row.platform_run_id}/stream`,
    });
  });
}
