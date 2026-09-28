/**
 * Observatory Projection Tests - M11.5
 * Validates timeline, graph, usage, wait, error and recovery projections; no raw prompt
 */

import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrateDatabase } from "../src/database.js";
import {
  buildObservatoryProjection,
  type ObservatoryEventRow,
  ObservatoryProjector,
  type ObservatoryRunRow,
  type ObservatorySource,
  type ObservatoryStepRow,
} from "../src/observatory.js";
import { REDACTED } from "../src/otel-observability.js";
import { RunLedger } from "../src/run-ledger.js";

const PROMPT = "PRIVATE PROMPT: summarize the salary spreadsheet";
const t = (seconds: number) => new Date(Date.UTC(2026, 8, 27, 12, 0, seconds));

function runRow(overrides: Partial<ObservatoryRunRow> = {}): ObservatoryRunRow {
  return {
    id: "run_1",
    workflow_id: "analytics",
    workflow_version: "1.0.0",
    status: "completed",
    error: null,
    attempt: 1,
    max_attempts: 3,
    cancel_requested: false,
    created_at: t(0),
    updated_at: t(30),
    finished_at: t(30),
    ...overrides,
  };
}

function step(overrides: Partial<ObservatoryStepRow> & { id: string }): ObservatoryStepRow {
  return {
    parent_step_id: null,
    kind: "agent",
    agent_id: "data",
    capability: "data.load",
    status: "completed",
    error: null,
    attempt: 0,
    created_at: t(2),
    started_at: t(2),
    finished_at: t(4),
    ...overrides,
  };
}

function event(
  seq: number,
  type: string,
  at: number,
  payload: Record<string, unknown> = {},
): ObservatoryEventRow {
  return { seq, event_type: type, payload: { ...payload, seq }, created_at: t(at) };
}

function source(overrides: Partial<ObservatorySource> = {}): ObservatorySource {
  return {
    run: runRow(),
    steps: [],
    events: [
      event(1, "run.queued", 0, { workflow_id: "analytics", workflow_version: "1.0.0" }),
      event(2, "run.leased", 3, { worker_id: "worker-a", attempt: 1 }),
      event(3, "run.status", 4, { from: "leased", to: "running", attempt: 1 }),
      event(4, "run.status", 30, {
        from: "running",
        to: "completed",
        attempt: 1,
        has_output: true,
      }),
    ],
    usage: [],
    ...overrides,
  };
}

describe("Observatory projection - M11.5", () => {
  describe("timeline", () => {
    it("orders events by seq and strips the internal seq from details", () => {
      const base = source();
      const projection = buildObservatoryProjection({
        ...base,
        events: [...base.events].reverse(),
      });

      expect(projection.timeline.map((entry) => entry.seq)).toEqual([1, 2, 3, 4]);
      expect(projection.timeline[1]).toEqual({
        seq: 2,
        type: "run.leased",
        at: t(3).toISOString(),
        detail: { worker_id: "worker-a", attempt: 1 },
      });
    });

    it("accepts pg bigint seq strings", () => {
      const projection = buildObservatoryProjection(
        source({ events: [{ ...event(7, "run.queued", 0), seq: "7" }] }),
      );
      expect(projection.timeline[0].seq).toBe(7);
    });

    it("reports run duration", () => {
      expect(buildObservatoryProjection(source()).run.durationMs).toBe(30_000);
      expect(
        buildObservatoryProjection(
          source({ run: runRow({ status: "running", finished_at: null }) }),
        ).run.durationMs,
      ).toBeNull();
    });
  });

  describe("no raw prompt", () => {
    it("drops raw content keys and masks sensitive keys in event details", () => {
      const projection = buildObservatoryProjection(
        source({
          events: [
            event(1, "agent.message", 1, {
              prompt: PROMPT,
              input: { question: PROMPT },
              output: { answer: PROMPT },
              messages: [{ role: "user", content: PROMPT }],
              api_key: "sk_live_should_not_leak",
              step_id: "step_1",
              nested: { content: PROMPT, note: "mail bob@example.com" },
            }),
          ],
        }),
      );

      const detail = projection.timeline[0].detail;
      expect(detail).toEqual({
        prompt: REDACTED,
        api_key: REDACTED,
        step_id: "step_1",
        nested: { note: `mail ${REDACTED}` },
      });
      expect(JSON.stringify(projection)).not.toMatch(/PRIVATE PROMPT|sk_live|bob@example\.com/);
    });

    it("truncates long strings and bounds depth", () => {
      let deep: Record<string, unknown> = { leaf: "value" };
      for (let index = 0; index < 10; index += 1) deep = { next: deep };
      const projection = buildObservatoryProjection(
        source({ events: [event(1, "note", 1, { note: "x ".repeat(400), deep })] }),
      );

      const detail = projection.timeline[0].detail as { note: string; deep: unknown };
      expect(detail.note.length).toBeLessThanOrEqual(201);
      expect(JSON.stringify(detail.deep)).toContain(REDACTED);
    });

    it("redacts error messages", () => {
      const projection = buildObservatoryProjection(
        source({
          run: runRow({
            status: "failed",
            error: "auth failed password=hunter2 for eve@example.com",
          }),
        }),
      );
      expect(projection.errors[0].message).not.toMatch(/hunter2|eve@example\.com/);
    });
  });

  describe("graph", () => {
    it("builds nodes, parent edges and roots", () => {
      const projection = buildObservatoryProjection(
        source({
          steps: [
            step({
              id: "plan",
              kind: "planner",
              agent_id: null,
              capability: null,
              started_at: t(1),
              finished_at: t(2),
            }),
            step({ id: "load", parent_step_id: "plan" }),
            step({
              id: "chart",
              parent_step_id: "plan",
              agent_id: "visualize",
              status: "running",
              finished_at: null,
            }),
            step({ id: "orphan", parent_step_id: "missing" }),
          ],
        }),
      );

      expect(projection.graph.edges).toEqual([
        { from: "plan", to: "load" },
        { from: "plan", to: "chart" },
      ]);
      expect(projection.graph.roots).toEqual(["plan", "orphan"]);
      const load = projection.graph.nodes.find((node) => node.id === "load");
      expect(load?.durationMs).toBe(2_000);
      expect(projection.graph.nodes.find((node) => node.id === "chart")?.durationMs).toBeNull();
    });
  });

  describe("usage", () => {
    it("totals tokens, latency and cost by kind, model and agent", () => {
      const projection = buildObservatoryProjection(
        source({
          usage: [
            {
              kind: "model",
              provider: "anthropic",
              model: "claude-sonnet-5",
              agent_id: "data",
              tool_name: null,
              input_tokens: 100,
              output_tokens: 40,
              latency_ms: 900,
              estimated_cost: "0.00120000",
            },
            {
              kind: "model",
              provider: "anthropic",
              model: "claude-sonnet-5",
              agent_id: "report",
              tool_name: null,
              input_tokens: 50,
              output_tokens: 10,
              latency_ms: 300,
              estimated_cost: "0.00030000",
            },
            {
              kind: "tool",
              provider: null,
              model: null,
              agent_id: "data",
              tool_name: "sql",
              input_tokens: null,
              output_tokens: null,
              latency_ms: 120,
              estimated_cost: null,
            },
          ],
        }),
      );

      expect(projection.usage.totals).toEqual({
        records: 3,
        inputTokens: 150,
        outputTokens: 50,
        latencyMs: 1_320,
        estimatedCost: 0.0015,
      });
      expect(projection.usage.byKind.tool.latencyMs).toBe(120);
      expect(projection.usage.byModel["anthropic/claude-sonnet-5"].records).toBe(2);
      expect(projection.usage.byAgent.data.records).toBe(2);
    });
  });

  describe("wait", () => {
    it("measures queue time and closed waiting intervals", () => {
      const projection = buildObservatoryProjection(
        source({
          steps: [step({ id: "approve", kind: "approval", status: "completed" })],
          events: [
            event(1, "run.queued", 0),
            event(2, "run.leased", 3, { worker_id: "worker-a" }),
            event(3, "run.status", 4, { from: "leased", to: "running" }),
            event(4, "run.status", 10, { from: "running", to: "waiting" }),
            event(5, "run.status", 25, { from: "waiting", to: "running" }),
            event(6, "run.status", 30, { from: "running", to: "completed" }),
          ],
        }),
      );

      expect(projection.wait.queuedMs).toBe(3_000);
      expect(projection.wait.waitingMs).toBe(15_000);
      expect(projection.wait.intervals).toEqual([
        { startedAt: t(10).toISOString(), endedAt: t(25).toISOString(), durationMs: 15_000 },
      ]);
    });

    it("keeps an open interval measured up to now", () => {
      const projection = buildObservatoryProjection(
        source({
          run: runRow({ status: "waiting", finished_at: null }),
          steps: [step({ id: "approve", kind: "approval", status: "waiting", finished_at: null })],
          events: [
            event(1, "run.queued", 0),
            event(2, "run.status", 10, { from: "running", to: "waiting" }),
          ],
        }),
        { now: t(40) },
      );

      expect(projection.wait.queuedMs).toBeNull();
      expect(projection.wait.intervals).toEqual([
        { startedAt: t(10).toISOString(), endedAt: null, durationMs: 30_000 },
      ]);
      expect(projection.wait.waitingSteps).toEqual(["approve"]);
    });
  });

  describe("errors and recovery", () => {
    it("collects event, step and run errors", () => {
      const projection = buildObservatoryProjection(
        source({
          run: runRow({ status: "failed", error: "run failed" }),
          steps: [step({ id: "load", status: "failed", error: "timeout" })],
          events: [
            event(1, "run.status", 5, { from: "running", to: "retryable", error: "worker lost" }),
          ],
        }),
      );

      expect(projection.errors.map((error) => [error.source, error.ref, error.message])).toEqual([
        ["event", "seq:1", "worker lost"],
        ["step", "load", "timeout"],
        ["run", "run_1", "run failed"],
      ]);
    });

    it("counts leases, retries and workers and marks recovered runs", () => {
      const projection = buildObservatoryProjection(
        source({
          run: runRow({ attempt: 2 }),
          events: [
            event(1, "run.queued", 0),
            event(2, "run.leased", 1, { worker_id: "worker-a", attempt: 1 }),
            event(3, "run.status", 5, { from: "running", to: "retryable", error: "lease expired" }),
            event(4, "run.status", 6, { from: "retryable", to: "queued" }),
            event(5, "run.leased", 7, { worker_id: "worker-b", attempt: 2 }),
            event(6, "run.status", 20, { from: "running", to: "completed" }),
          ],
        }),
      );

      expect(projection.recovery).toEqual({
        attempts: 2,
        maxAttempts: 3,
        leases: 2,
        retries: 1,
        workers: ["worker-a", "worker-b"],
        cancelRequested: false,
        recovered: true,
      });
    });

    it("reports cancellation requests", () => {
      const projection = buildObservatoryProjection(
        source({ events: [event(1, "run.cancel_requested", 2, { run_id: "run_1" })] }),
      );
      expect(projection.recovery.cancelRequested).toBe(true);
      expect(projection.recovery.recovered).toBe(false);
    });
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("Observatory projection - M11.5 (PostgreSQL)", () => {
  let database: Pool;
  let ledger: RunLedger;
  let projector: ObservatoryProjector;

  beforeAll(async () => {
    database = new Pool({ connectionString: databaseUrl, max: 4 });
    await migrateDatabase(database);
    ledger = new RunLedger(database);
    projector = new ObservatoryProjector(database);
  });

  afterAll(async () => {
    await database?.end();
  });

  it("projects a ledger run without exposing input, output or prompts", async () => {
    const scope = { spaceId: `space_${randomUUID()}`, userId: `user_${randomUUID()}` };
    const created = await ledger.create({
      ...scope,
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      input: { prompt: PROMPT },
      idempotencyKey: randomUUID(),
    });
    try {
      const workerId = `worker_${randomUUID()}`;
      let claimed = await ledger.claim(workerId);
      while (claimed && claimed.id !== created.id) claimed = await ledger.claim(workerId);
      expect(claimed?.id).toBe(created.id);
      const token = claimed!.fencing_token;

      await ledger.transition(created.id, workerId, token, "leased", "running");
      await database.query(
        `INSERT INTO platform_run_steps (id, run_id, kind, agent_id, capability, status, input, output, started_at, finished_at)
         VALUES ($1, $2, 'agent', 'data', 'data.load', 'completed', $3::jsonb, $3::jsonb, now(), now())`,
        [`step_${randomUUID()}`, created.id, JSON.stringify({ prompt: PROMPT })],
      );
      await ledger.recordUsage({
        runId: created.id,
        ...scope,
        kind: "model",
        provider: "anthropic",
        model: "claude-sonnet-5",
        agentId: "data",
        inputTokens: 120,
        outputTokens: 30,
        latencyMs: 800,
        estimatedCost: 0.0012,
        metadata: { prompt: PROMPT },
      });
      await ledger.transition(created.id, workerId, token, "running", "completed", {
        output: { answer: PROMPT },
      });

      const projection = await projector.get(created.id, scope);
      expect(projection).not.toBeNull();
      expect(projection!.run.status).toBe("completed");
      expect(projection!.timeline.map((entry) => entry.type)).toEqual([
        "run.queued",
        "run.leased",
        "run.status",
        "run.status",
      ]);
      expect(projection!.graph.nodes).toHaveLength(1);
      expect(projection!.usage.totals).toMatchObject({
        inputTokens: 120,
        outputTokens: 30,
        estimatedCost: 0.0012,
      });
      expect(projection!.wait.queuedMs).not.toBeNull();
      expect(projection!.recovery.leases).toBe(1);
      expect(JSON.stringify(projection)).not.toContain("PRIVATE PROMPT");

      expect(await projector.get(created.id, { ...scope, userId: "someone_else" })).toBeNull();
    } finally {
      await database.query("DELETE FROM platform_runs WHERE id = $1", [created.id]);
    }
  });
});
