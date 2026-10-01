/**
 * Observatory projection - M11.5
 * Read-only run view: timeline, graph, usage, wait, error, recovery; no raw prompt.
 *
 * The projection is derived from the canonical ledger (platform_runs, platform_run_steps,
 * platform_run_events, platform_usage_records). It never selects run/step input or output
 * columns, and event payloads are sanitized before they are returned, so prompts and model
 * payloads cannot reach a viewer. Disabling the projection has no effect on the ledger.
 */

import type { Pool } from "pg";
import { isSensitiveKey, REDACTED, redactText } from "./otel-observability.js";
import type { RunStatus } from "./run-state.js";

export interface ObservatoryScope {
  spaceId: string;
  userId: string;
}

export interface ObservatoryRunRow {
  id: string;
  workflow_id: string;
  workflow_version: string;
  status: RunStatus;
  error: string | null;
  attempt: number;
  max_attempts: number;
  cancel_requested: boolean;
  created_at: Date;
  updated_at: Date;
  finished_at: Date | null;
}

export interface ObservatoryStepRow {
  id: string;
  parent_step_id: string | null;
  kind: "planner" | "agent" | "tool" | "approval";
  agent_id: string | null;
  capability: string | null;
  status: "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled";
  error: string | null;
  attempt: number;
  created_at: Date;
  started_at: Date | null;
  finished_at: Date | null;
}

export interface ObservatoryEventRow {
  seq: number | string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: Date;
}

export interface ObservatoryUsageRow {
  kind: "model" | "tool" | "sandbox" | "worker";
  provider: string | null;
  model: string | null;
  agent_id: string | null;
  tool_name: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  estimated_cost: string | number | null;
}

export interface ObservatorySource {
  run: ObservatoryRunRow;
  steps: ObservatoryStepRow[];
  events: ObservatoryEventRow[];
  usage: ObservatoryUsageRow[];
}

export interface TimelineEntry {
  seq: number;
  type: string;
  at: string;
  detail: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  kind: ObservatoryStepRow["kind"];
  agentId: string | null;
  capability: string | null;
  status: ObservatoryStepRow["status"];
  attempt: number;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
}

export interface UsageTotals {
  records: number;
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
  estimatedCost: number;
}

export interface WaitInterval {
  startedAt: string;
  endedAt: string | null;
  durationMs: number;
}

export interface ObservatoryError {
  source: "run" | "step" | "event";
  ref: string;
  message: string;
  at: string;
}

export interface ObservatoryProjection {
  run: {
    id: string;
    workflowId: string;
    workflowVersion: string;
    status: RunStatus;
    createdAt: string;
    updatedAt: string;
    finishedAt: string | null;
    durationMs: number | null;
  };
  timeline: TimelineEntry[];
  graph: { nodes: GraphNode[]; edges: Array<{ from: string; to: string }>; roots: string[] };
  usage: {
    totals: UsageTotals;
    byKind: Record<string, UsageTotals>;
    byModel: Record<string, UsageTotals>;
    byAgent: Record<string, UsageTotals>;
  };
  wait: {
    queuedMs: number | null;
    waitingMs: number;
    intervals: WaitInterval[];
    waitingSteps: string[];
  };
  errors: ObservatoryError[];
  recovery: {
    attempts: number;
    maxAttempts: number;
    leases: number;
    retries: number;
    workers: string[];
    cancelRequested: boolean;
    recovered: boolean;
  };
  /** True when the event list hit the load limit and the timeline is partial. */
  truncated: boolean;
}

/** Keys that can carry raw prompts or model/tool payloads; removed from event details. */
const RAW_CONTENT_KEY =
  /^(input|output|content|messages?|text|body|arguments|result|response|completion)$/i;
const MAX_DETAIL_DEPTH = 4;
const MAX_DETAIL_STRING = 200;
const MAX_ERROR_MESSAGE = 500;
export const MAX_PROJECTED_EVENTS = 1000;

/** Build the projection from already-loaded ledger rows. `now` bounds open intervals. */
export function buildObservatoryProjection(
  source: ObservatorySource,
  options: { now?: Date; truncated?: boolean } = {},
): ObservatoryProjection {
  const now = options.now ?? new Date();
  const { run } = source;
  const events = [...source.events]
    .map((event) => ({ ...event, seq: Number(event.seq) }))
    .sort((left, right) => left.seq - right.seq);

  return {
    run: {
      id: run.id,
      workflowId: run.workflow_id,
      workflowVersion: run.workflow_version,
      status: run.status,
      createdAt: iso(run.created_at),
      updatedAt: iso(run.updated_at),
      finishedAt: run.finished_at ? iso(run.finished_at) : null,
      durationMs: run.finished_at ? elapsed(run.created_at, run.finished_at) : null,
    },
    timeline: events.map((event) => ({
      seq: event.seq,
      type: event.event_type,
      at: iso(event.created_at),
      detail: sanitizeDetail(withoutSeq(event.payload), 0),
    })),
    graph: projectGraph(source.steps),
    usage: projectUsage(source.usage),
    wait: projectWait(run, source.steps, events, now),
    errors: projectErrors(run, source.steps, events),
    recovery: projectRecovery(run, events),
    truncated: options.truncated ?? false,
  };
}

/** Loads ledger rows for one run, scoped to its owner, and builds the projection. */
export class ObservatoryProjector {
  constructor(private readonly pool: Pool) {}

  /** Returns null when the run does not exist or is outside the caller's scope. */
  async get(
    runId: string,
    scope: ObservatoryScope,
    now = new Date(),
  ): Promise<ObservatoryProjection | null> {
    // Explicit column lists: input/output are never read into the projection.
    const runResult = await this.pool.query<ObservatoryRunRow>(
      `SELECT id, workflow_id, workflow_version, status, error, attempt, max_attempts,
              cancel_requested, created_at, updated_at, finished_at
       FROM platform_runs
       WHERE id = $1 AND space_id = $2 AND user_id = $3`,
      [runId, scope.spaceId, scope.userId],
    );
    const run = runResult.rows[0];
    if (!run) return null;

    const [steps, events, usage] = await Promise.all([
      this.pool.query<ObservatoryStepRow>(
        `SELECT id, parent_step_id, kind, agent_id, capability, status, error, attempt,
                created_at, started_at, finished_at
         FROM platform_run_steps WHERE run_id = $1 ORDER BY created_at, id`,
        [runId],
      ),
      this.pool.query<ObservatoryEventRow>(
        `SELECT seq, event_type, payload, created_at
         FROM platform_run_events WHERE run_id = $1 ORDER BY seq LIMIT $2`,
        [runId, MAX_PROJECTED_EVENTS + 1],
      ),
      this.pool.query<ObservatoryUsageRow>(
        `SELECT kind, provider, model, agent_id, tool_name, input_tokens, output_tokens,
                latency_ms, estimated_cost
         FROM platform_usage_records WHERE run_id = $1`,
        [runId],
      ),
    ]);

    const truncated = events.rows.length > MAX_PROJECTED_EVENTS;
    return buildObservatoryProjection(
      {
        run,
        steps: steps.rows,
        events: events.rows.slice(0, MAX_PROJECTED_EVENTS),
        usage: usage.rows,
      },
      { now, truncated },
    );
  }
}

function projectGraph(steps: ObservatoryStepRow[]): ObservatoryProjection["graph"] {
  const ids = new Set(steps.map((step) => step.id));
  const nodes = steps.map((step) => ({
    id: step.id,
    kind: step.kind,
    agentId: step.agent_id,
    capability: step.capability,
    status: step.status,
    attempt: step.attempt,
    startedAt: step.started_at ? iso(step.started_at) : null,
    finishedAt: step.finished_at ? iso(step.finished_at) : null,
    durationMs:
      step.started_at && step.finished_at ? elapsed(step.started_at, step.finished_at) : null,
  }));
  const edges = steps
    .filter((step) => step.parent_step_id !== null && ids.has(step.parent_step_id))
    .map((step) => ({ from: step.parent_step_id as string, to: step.id }));
  const roots = steps
    .filter((step) => step.parent_step_id === null || !ids.has(step.parent_step_id))
    .map((step) => step.id);
  return { nodes, edges, roots };
}

function projectUsage(rows: ObservatoryUsageRow[]): ObservatoryProjection["usage"] {
  const totals = emptyTotals();
  const byKind: Record<string, UsageTotals> = {};
  const byModel: Record<string, UsageTotals> = {};
  const byAgent: Record<string, UsageTotals> = {};
  for (const row of rows) {
    add(totals, row);
    add(bucket(byKind, row.kind), row);
    if (row.model)
      add(bucket(byModel, row.provider ? `${row.provider}/${row.model}` : row.model), row);
    if (row.agent_id) add(bucket(byAgent, row.agent_id), row);
  }
  return { totals, byKind, byModel, byAgent };
}

function bucket(group: Record<string, UsageTotals>, key: string): UsageTotals {
  group[key] ??= emptyTotals();
  return group[key];
}

function projectWait(
  run: ObservatoryRunRow,
  steps: ObservatoryStepRow[],
  events: Array<ObservatoryEventRow & { seq: number }>,
  now: Date,
): ObservatoryProjection["wait"] {
  const firstLease = events.find((event) => event.event_type === "run.leased");
  const queuedMs = firstLease ? elapsed(run.created_at, firstLease.created_at) : null;

  const intervals: WaitInterval[] = [];
  let open: Date | null = null;
  for (const event of events) {
    if (event.event_type !== "run.status") continue;
    const to = event.payload.to;
    if (open && to !== "waiting") {
      intervals.push(interval(open, event.created_at));
      open = null;
    }
    if (to === "waiting" && !open) open = event.created_at;
  }
  if (open) {
    const end = run.finished_at ?? null;
    intervals.push(
      end
        ? interval(open, end)
        : { startedAt: iso(open), endedAt: null, durationMs: elapsed(open, now) },
    );
  }

  return {
    queuedMs,
    waitingMs: intervals.reduce((sum, item) => sum + item.durationMs, 0),
    intervals,
    waitingSteps: steps.filter((step) => step.status === "waiting").map((step) => step.id),
  };
}

function projectErrors(
  run: ObservatoryRunRow,
  steps: ObservatoryStepRow[],
  events: Array<ObservatoryEventRow & { seq: number }>,
): ObservatoryError[] {
  const errors: ObservatoryError[] = [];
  for (const event of events) {
    if (event.event_type === "run.status" && typeof event.payload.error === "string") {
      errors.push({
        source: "event",
        ref: `seq:${event.seq}`,
        message: safeMessage(event.payload.error),
        at: iso(event.created_at),
      });
    }
  }
  for (const step of steps) {
    if (step.error) {
      errors.push({
        source: "step",
        ref: step.id,
        message: safeMessage(step.error),
        at: iso(step.finished_at ?? step.started_at ?? step.created_at),
      });
    }
  }
  if (run.error) {
    errors.push({
      source: "run",
      ref: run.id,
      message: safeMessage(run.error),
      at: iso(run.finished_at ?? run.updated_at),
    });
  }
  return errors;
}

function projectRecovery(
  run: ObservatoryRunRow,
  events: Array<ObservatoryEventRow & { seq: number }>,
): ObservatoryProjection["recovery"] {
  const leases = events.filter((event) => event.event_type === "run.leased");
  const retries = events.filter(
    (event) => event.event_type === "run.status" && event.payload.to === "retryable",
  ).length;
  const workers = [
    ...new Set(
      leases
        .map((event) => event.payload.worker_id)
        .filter((worker): worker is string => typeof worker === "string")
        .map((worker) => redactText(worker)),
    ),
  ];
  return {
    attempts: run.attempt,
    maxAttempts: run.max_attempts,
    leases: leases.length,
    retries,
    workers,
    cancelRequested:
      run.cancel_requested || events.some((event) => event.event_type === "run.cancel_requested"),
    recovered: retries > 0 && run.status === "completed",
  };
}

/** Drops raw-content keys, masks sensitive keys and redacts/truncates strings. */
function sanitizeDetail(value: Record<string, unknown>, depth: number): Record<string, unknown> {
  const detail: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (RAW_CONTENT_KEY.test(key)) continue;
    detail[key] = isSensitiveKey(key) ? REDACTED : sanitizeValue(item, depth + 1);
  }
  return detail;
}

function sanitizeValue(value: unknown, depth: number): unknown {
  if (typeof value === "string") return truncate(redactText(value), MAX_DETAIL_STRING);
  if (value === null || typeof value !== "object") return value;
  if (depth >= MAX_DETAIL_DEPTH) return REDACTED;
  if (Array.isArray(value)) return value.map((item) => sanitizeValue(item, depth + 1));
  return sanitizeDetail(value as Record<string, unknown>, depth);
}

function withoutSeq(payload: Record<string, unknown>): Record<string, unknown> {
  const { seq: _seq, ...rest } = payload ?? {};
  return rest;
}

function safeMessage(message: string): string {
  return truncate(redactText(message), MAX_ERROR_MESSAGE);
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function emptyTotals(): UsageTotals {
  return { records: 0, inputTokens: 0, outputTokens: 0, latencyMs: 0, estimatedCost: 0 };
}

function add(totals: UsageTotals, row: ObservatoryUsageRow): void {
  totals.records += 1;
  totals.inputTokens += row.input_tokens ?? 0;
  totals.outputTokens += row.output_tokens ?? 0;
  totals.latencyMs += row.latency_ms ?? 0;
  // numeric(20,8) arrives from pg as a string
  totals.estimatedCost = roundCost(totals.estimatedCost + Number(row.estimated_cost ?? 0));
}

function roundCost(value: number): number {
  return Math.round(value * 1e8) / 1e8;
}

function interval(start: Date, end: Date): WaitInterval {
  return { startedAt: iso(start), endedAt: iso(end), durationMs: elapsed(start, end) };
}

function elapsed(start: Date, end: Date): number {
  return Math.max(0, new Date(end).getTime() - new Date(start).getTime());
}

function iso(value: Date): string {
  return new Date(value).toISOString();
}
