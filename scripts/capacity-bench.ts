/**
 * M13.3 local capacity bench.
 *
 * Exercises the real code paths (Hono app + v1 API, RunLedger, DurableRunWorker,
 * McpToolPool, PostgresAgentMemoryProvider, ArtifactStorage) against a disposable
 * PostgreSQL database. The model is a fake with fixed latency and token counts, so
 * "cost" is computed from a stated price table, not measured from a provider.
 *
 *   tsx scripts/capacity-bench.ts <database-url-containing-"rehearsal"> [scale]
 *
 * Prints one JSON receipt to stdout. Every section also asserts correctness under
 * load (no lost or double-executed run); a throughput number without that is noise.
 */

import os from "node:os";
import { Hono } from "hono";
import { Pool } from "pg";
import { Type } from "typebox";
import { ArtifactStorage } from "../src/artifact-storage.js";
import { migrateDatabase } from "../src/database.js";
import { registerPlatformApi } from "../src/platform-api.js";
import { PostgresAgentMemoryProvider } from "../src/postgres-store.js";
import { AgentPool } from "../src/registry.js";
import { RunLedger } from "../src/run-ledger.js";
import { DurableRunWorker } from "../src/run-worker.js";
import { McpToolPool } from "../src/tool-pool.js";
import { issueWebSession } from "../src/web-auth.js";

/** Stated, not measured: USD per 1M tokens for the fake model profile. */
const PRICE_PER_MTOK = { input: 3, output: 15 };
const FAKE_MODEL = { latencyMs: 40, inputTokens: 1_200, outputTokens: 300 };

const url = process.argv[2];
const scale = Number(process.argv[3] ?? 1);
if (!url || !new URL(url).pathname.includes("rehearsal")) {
  throw new Error(
    'usage: capacity-bench.ts <database url whose name contains "rehearsal"> [scale]',
  );
}

type Stats = { n: number; p50: number; p95: number; p99: number; max: number; mean: number };

function stats(samples: number[]): Stats {
  const sorted = [...samples].sort((left, right) => left - right);
  const at = (q: number) =>
    sorted[Math.min(sorted.length - 1, Math.ceil(q * sorted.length) - 1)] ?? 0;
  const round = (value: number) => Math.round(value * 100) / 100;
  return {
    n: sorted.length,
    p50: round(at(0.5)),
    p95: round(at(0.95)),
    p99: round(at(0.99)),
    max: round(sorted.at(-1) ?? 0),
    mean: round(sorted.reduce((sum, value) => sum + value, 0) / Math.max(1, sorted.length)),
  };
}

async function timed<T>(samples: number[], fn: () => Promise<T>): Promise<T> {
  const started = performance.now();
  try {
    return await fn();
  } finally {
    samples.push(performance.now() - started);
  }
}

/** Run `total` tasks with at most `concurrency` in flight. */
async function pool<T>(
  total: number,
  concurrency: number,
  task: (index: number) => Promise<T>,
): Promise<T[]> {
  const results: T[] = new Array(total);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(concurrency, total) }, async () => {
      while (next < total) {
        const index = next++;
        results[index] = await task(index);
      }
    }),
  );
  return results;
}

const database = new Pool({ connectionString: url, max: 40 });
await migrateDatabase(database);
const ledger = new RunLedger(database);
const space = "bench-space";
const user = "bench-user";
await database.query("INSERT INTO web_users (id, name) VALUES ($1, $1) ON CONFLICT DO NOTHING", [
  user,
]);
const sections: Record<string, unknown> = {};

// ---- API: create + read through the real HTTP stack --------------------------
{
  const webAuth = {
    mode: "session" as const,
    secret: "capacity-bench-signing-key-000000",
    ttlSeconds: 3_600,
  };
  const app = new Hono();
  registerPlatformApi(app, {
    database,
    pluginRegistry: new AgentPool(),
    webAuth,
    runLedger: ledger,
  });
  const headers = {
    Authorization: `Bearer ${issueWebSession(user, webAuth)}`,
    "X-Space-Id": space,
    "Content-Type": "application/json",
  };
  for (const concurrency of [1, 8, 32]) {
    const create: number[] = [];
    const read: number[] = [];
    let errors = 0;
    const total = 200 * scale;
    const started = performance.now();
    await pool(total, concurrency, async (index) => {
      const response = await timed(create, () =>
        app.request("/api/v1/runs", {
          method: "POST",
          headers,
          body: JSON.stringify({
            workflow_id: "bench.noop",
            idempotency_key: `api-${concurrency}-${index}`,
            input: { index },
          }),
        }),
      );
      if (response.status !== 202) errors += 1;
      const { run_id: runId } = (await response.json()) as { run_id: string };
      const detail = await timed(read, () => app.request(`/api/v1/runs/${runId}`, { headers }));
      if (detail.status !== 200) errors += 1;
    });
    const seconds = (performance.now() - started) / 1_000;
    sections[`api_c${concurrency}`] = {
      requests: total * 2,
      errors,
      throughput_rps: Math.round((total * 2) / seconds),
      create_ms: stats(create),
      read_ms: stats(read),
    };
  }
  // Leave the queue empty for the worker section.
  await database.query(
    "UPDATE platform_runs SET status = 'cancelled', cancel_requested = true WHERE workflow_id = 'bench.noop'",
  );
}

// ---- Worker + child fan-out: several workers competing for one queue ---------
{
  const parents = 20 * scale;
  const fanOut = 8;
  const executions = new Map<string, number>();
  const queueLatency: number[] = [];
  const modelCalls: number[] = [];
  let tokensIn = 0;
  let tokensOut = 0;

  const created = new Map<string, number>();
  const createFanOut: number[] = [];
  const started = performance.now();
  await pool(parents, 10, async (index) => {
    await timed(createFanOut, async () => {
      const client = await database.connect();
      try {
        await client.query("BEGIN");
        for (let child = 0; child < fanOut; child += 1) {
          const run = await ledger.createOnClient(client, {
            spaceId: space,
            userId: user,
            workflowId: "bench.child",
            workflowVersion: "1",
            input: { parent: index, child },
            idempotencyKey: `child-${index}-${child}`,
          });
          created.set(run.id, performance.now());
        }
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    });
  });

  const executor = {
    async execute(run: { id: string; space_id: string; user_id: string }) {
      executions.set(run.id, (executions.get(run.id) ?? 0) + 1);
      const enqueued = created.get(run.id);
      if (enqueued) queueLatency.push(performance.now() - enqueued);
      await timed(
        modelCalls,
        () => new Promise((resolve) => setTimeout(resolve, FAKE_MODEL.latencyMs)),
      );
      tokensIn += FAKE_MODEL.inputTokens;
      tokensOut += FAKE_MODEL.outputTokens;
      await ledger.recordUsage({
        runId: run.id,
        userId: run.user_id,
        spaceId: run.space_id,
        kind: "model",
        provider: "fake",
        model: "bench-profile",
        inputTokens: FAKE_MODEL.inputTokens,
        outputTokens: FAKE_MODEL.outputTokens,
        latencyMs: FAKE_MODEL.latencyMs,
        estimatedCost:
          (FAKE_MODEL.inputTokens * PRICE_PER_MTOK.input +
            FAKE_MODEL.outputTokens * PRICE_PER_MTOK.output) /
          1_000_000,
      });
      return { ok: true };
    },
  };
  const workers = Array.from(
    { length: 4 },
    (_, index) =>
      new DurableRunWorker(ledger, executor as never, {
        workerId: `bench-${index}`,
        concurrency: 8,
        pollMs: 10,
      }),
  );
  for (const worker of workers) worker.start();
  const total = parents * fanOut;
  for (;;) {
    const done = await database.query<{ n: number }>(
      "SELECT count(*)::int AS n FROM platform_runs WHERE workflow_id = 'bench.child' AND status = 'completed'",
    );
    if (done.rows[0].n >= total || performance.now() - started > 300_000) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  await Promise.all(workers.map((worker) => worker.drain(5_000)));
  const seconds = (performance.now() - started) / 1_000;
  const final = await database.query<{ status: string; n: number }>(
    "SELECT status, count(*)::int AS n FROM platform_runs WHERE workflow_id = 'bench.child' GROUP BY status",
  );
  const cost = await database.query<{ total: string }>(
    "SELECT coalesce(sum(estimated_cost), 0) AS total FROM platform_usage_records WHERE space_id = $1",
    [space],
  );
  const doubled = [...executions.values()].filter((count) => count > 1).length;
  sections.worker_fanout = {
    parents,
    fan_out: fanOut,
    runs: total,
    workers: 4,
    per_worker_concurrency: 8,
    statuses: Object.fromEntries(final.rows.map((row) => [row.status, row.n])),
    executed_once: executions.size,
    executed_twice_or_more: doubled,
    lost: total - executions.size,
    throughput_runs_per_s: Math.round(total / seconds),
    fan_out_create_ms: stats(createFanOut),
    queue_to_start_ms: stats(queueLatency),
    fake_model_ms: stats(modelCalls),
    cost: {
      price_per_mtok_usd: PRICE_PER_MTOK,
      tokens: { input: tokensIn, output: tokensOut },
      total_usd: Number(Number(cost.rows[0].total).toFixed(6)),
      per_run_usd: Number((Number(cost.rows[0].total) / total).toFixed(6)),
    },
  };
}

// ---- Tool pool: authorization + schema validation + timeout wrapper ---------
{
  const tools = new McpToolPool();
  tools.register({
    name: "bench.echo",
    description: "echo",
    schema: Type.Object({ value: Type.String(), n: Type.Number() }),
    mutates: false,
    agents: ["bench"],
    authorize: () => true,
    execute: async (input) => input,
  });
  const samples: number[] = [];
  const controller = new AbortController();
  await pool(5_000 * scale, 16, (index) =>
    timed(samples, () =>
      tools.call(
        "bench.echo",
        { value: "x", n: index },
        { userId: user, spaceId: space, signal: controller.signal },
        "bench",
      ),
    ),
  );
  sections.tool_call_overhead = { calls: samples.length, ms: stats(samples) };
}

// ---- Memory: scoped writes then searches on a growing store -----------------
{
  const memory = new PostgresAgentMemoryProvider(database);
  const scope = {
    userId: user,
    spaceId: space,
    agentId: "bench",
    signal: new AbortController().signal,
  };
  const write: number[] = [];
  const search: number[] = [];
  await pool(500 * scale, 8, (index) =>
    timed(write, () =>
      memory.remember(
        {
          text: `fact ${index}: revenue in region ${index % 17} was ${index * 3}`,
          tags: ["bench"],
        },
        scope,
      ),
    ),
  );
  await pool(300 * scale, 8, (index) =>
    timed(search, () => memory.search(`region ${index % 17}`, scope)),
  );
  sections.memory = { entries: write.length, remember_ms: stats(write), search_ms: stats(search) };
}

// ---- Artifacts: metadata-first write with hash readback, then read ----------
{
  const artifacts = new ArtifactStorage(database);
  const results: Record<string, unknown> = {};
  for (const [label, bytes] of [
    ["1KB", 1_024],
    ["256KB", 262_144],
    ["1MB", 1_048_576],
  ] as const) {
    const store: number[] = [];
    const read: number[] = [];
    const content = Buffer.alloc(bytes, 7);
    const count = (label === "1MB" ? 20 : 100) * scale;
    let mismatches = 0;
    const ids = await pool(count, 4, (index) =>
      timed(store, () =>
        artifacts.store({
          workspaceId: space,
          ownerRunId: `bench-run-${label}-${index}`,
          kind: "dataset",
          version: "1",
          content,
        }),
      ),
    );
    await pool(ids.length, 4, async (index) => {
      const got = await timed(read, () => artifacts.getContent(ids[index].id, space));
      if (!got || got.length !== bytes) mismatches += 1;
    });
    results[label] = { count, mismatches, store_ms: stats(store), read_ms: stats(read) };
  }
  sections.artifacts = results;
}

const server = await database.query<{ server_version: string }>("SHOW server_version");
await database.end();
process.stdout.write(
  `${JSON.stringify(
    {
      milestone: "M13.3",
      kind: "local-capacity-bench",
      at: new Date().toISOString(),
      scale,
      environment: {
        node: process.version,
        cpus: os.cpus().length,
        cpu_model: os.cpus()[0]?.model,
        memory_gb: Math.round(os.totalmem() / 1024 ** 3),
        postgres: server.rows[0].server_version,
        note: "single host, API/worker in one process, PostgreSQL in a local container; not a production figure",
      },
      model: { kind: "fake", ...FAKE_MODEL },
      sections,
    },
    null,
    2,
  )}\n`,
);
