/**
 * Live end-to-end benchmark: real API server + durable worker processes, real model provider
 * (MODEL_API_KEY from .env), disposable pinned PostgreSQL. Each scenario goes through the public
 * web API exactly like the UI: create user → post message → poll task until terminal. Latency is
 * wall-clock from POST to terminal task; tokens/cost come from platform_usage_records written by
 * PiRuntime (provider-reported usage), not from estimates.
 *
 *   pnpm exec tsx scripts/e2e-benchmark.ts [--repeat 3] [--budget 0.30]
 *
 * Writes docs/execution/live/e2e-benchmark-<timestamp>.json. Only MODEL_API_KEY is read from .env
 * and it is never printed. The run stops before a scenario once spent cost reaches the budget.
 */
import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { Pool } from "pg";

const IMAGE = "postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193";
const args = process.argv.slice(2);
const flag = (name: string, fallback: number) => {
  const index = args.indexOf(`--${name}`);
  return index >= 0 ? Number(args[index + 1]) : fallback;
};
const repeat = flag("repeat", 3);
const budgetUsd = flag("budget", 0.3);
const taskTimeoutMs = flag("timeout-ms", 180_000);

const SCENARIOS = [
  { id: "greeting", agent: "orchestrator", content: "Hi! In one sentence, what can you do?" },
  {
    id: "warehouse-discovery",
    agent: "data",
    content: "List the tables available in the sample warehouse and their row counts.",
  },
  {
    id: "planned-analytics",
    agent: "orchestrator",
    content: "Which region had the highest total revenue in monthly_sales? Cite the dataset.",
  },
] as const;

function modelKey(): string {
  const existing = process.env.MODEL_API_KEY?.trim();
  if (existing) return existing;
  const line = readFileSync(".env", "utf8")
    .split(/\r?\n/)
    .find((entry) => /^(MODEL_API_KEY|OPENAI_API_KEY)=/.test(entry));
  const value = line?.slice(line.indexOf("=") + 1).trim();
  if (!value) throw new Error("MODEL_API_KEY or OPENAI_API_KEY is required in .env");
  return value;
}

const docker = (argv: string[], env: NodeJS.ProcessEnv = {}) =>
  spawnSync("docker", argv, { encoding: "utf8", env: { ...process.env, ...env } });
function must(result: ReturnType<typeof docker>, step: string): string {
  if (result.status !== 0) throw new Error(`${step} failed: ${result.stderr.trim().slice(0, 300)}`);
  return result.stdout.trim();
}

async function startDatabase(name: string, password: string): Promise<string> {
  must(docker(["image", "inspect", IMAGE]), "pinned PostgreSQL image lookup");
  must(
    docker(
      [
        "run",
        "--detach",
        "--pull=never",
        "--name",
        name,
        "--label",
        "team6.purpose=e2e-benchmark",
        "--memory=512m",
        "--tmpfs",
        "/var/lib/postgresql/data:rw,size=384m",
        "--publish",
        "127.0.0.1::5432",
        // Password travels via the environment, never on the docker command line.
        "--env",
        "POSTGRES_PASSWORD",
        "--env",
        "POSTGRES_DB=team6_e2e",
        IMAGE,
      ],
      { POSTGRES_PASSWORD: password },
    ),
    "disposable PostgreSQL start",
  );
  const binding = must(docker(["port", name, "5432/tcp"]), "port lookup").split("\n")[0] ?? "";
  if (!/^127\.0\.0\.1:\d+$/.test(binding)) throw new Error("unexpected database port binding");
  for (let attempt = 0; attempt < 60; attempt++) {
    if (docker(["exec", name, "pg_isready", "-U", "postgres", "-d", "team6_e2e"]).status === 0) {
      return `postgres://postgres:${password}@${binding}/team6_e2e`;
    }
    await sleep(500);
  }
  throw new Error("disposable PostgreSQL readiness timed out");
}

function launch(script: string, env: NodeJS.ProcessEnv, log: string[]): ChildProcess {
  // node --import tsx (not `pnpm exec`) so SIGTERM reaches the process that owns the lifecycle.
  const child = spawn(process.execPath, ["--import", "tsx", script], {
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const keep = (chunk: Buffer) => {
    for (const line of chunk.toString().split("\n")) if (line.trim()) log.push(line.slice(0, 300));
    if (log.length > 400) log.splice(0, log.length - 400);
  };
  child.stdout?.on("data", keep);
  child.stderr?.on("data", keep);
  return child;
}

async function waitFor(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ok = await fetch(url)
      .then((response) => response.ok)
      .catch(() => false);
    if (ok) return;
    await sleep(500);
  }
  throw new Error(`${url} did not become ready`);
}

function percentile(values: number[], p: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)] ?? 0;
}
/** Deterministic answer checks per scenario; the mock warehouse fixes the ground truth. */
function checks(id: string, answer: string, delegations: number): Record<string, boolean> {
  const text = answer.toLowerCase();
  if (id === "greeting") return { nonEmpty: answer.trim().length > 0 };
  if (id === "warehouse-discovery") {
    return { monthlySales: text.includes("monthly_sales"), customers: text.includes("customers") };
  }
  // North: 120 + 145 = 265 vs South: 98 + 91 = 189.
  return {
    north: /\bnorth\b/.test(text),
    citesDataset: /\bds_(?:[a-z0-9]{12}|[a-f0-9]{24})\b/i.test(answer),
    delegated: delegations > 0,
  };
}

type Sample = {
  scenario: string;
  iteration: number;
  taskStatus: string;
  latencyMs: number;
  invocations: number;
  delegations: number;
  modelCalls: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  checks: Record<string, boolean>;
  answerPreview: string;
};

const name = `team6-e2e-${randomUUID().slice(0, 8)}`;
const children: ChildProcess[] = [];
const log: string[] = [];
let database: Pool | undefined;
try {
  const databaseUrl = await startDatabase(name, randomBytes(18).toString("hex"));
  const port = 3100 + Math.floor(Math.random() * 800);
  const base = `http://127.0.0.1:${port}`;
  const env: NodeJS.ProcessEnv = {
    PATH: process.env.PATH,
    HOME: process.env.HOME,
    DATABASE_URL: databaseUrl,
    API_TOKEN: randomBytes(24).toString("hex"),
    MODEL_API_KEY: modelKey(),
    PORT: String(port),
    PLATFORM_RUNNER_MODE: "api",
    ALERT_EVAL_INTERVAL_MS: "0",
    WORKER_POLL_MS: "100",
    RATE_LIMIT_REQUESTS_PER_MINUTE: "10000",
  };
  // Server migrates first; the worker starts after readiness so both never race the lock.
  children.push(launch("src/server.ts", env, log));
  await waitFor(`${base}/ready`, 90_000);
  children.push(launch("src/worker.ts", { ...env, WORKER_ID: "e2e-worker" }, log));
  await sleep(3_000);
  database = new Pool({ connectionString: databaseUrl, max: 2 });

  const user = (await (
    await fetch(`${base}/api/users`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "e2e-benchmark" }),
    })
  ).json()) as { id: string };
  const headers = { "content-type": "application/json", "x-user-id": user.id };

  const samples: Sample[] = [];
  const skipped: string[] = [];
  let spent = 0;
  for (let iteration = 1; iteration <= repeat; iteration++) {
    for (const scenario of SCENARIOS) {
      if (spent >= budgetUsd) {
        skipped.push(`${scenario.id}#${iteration}`);
        continue;
      }
      const since = new Date();
      const started = performance.now();
      const posted = await fetch(`${base}/api/agents/${scenario.agent}/messages`, {
        method: "POST",
        headers,
        body: JSON.stringify({ content: scenario.content }),
      });
      if (posted.status !== 202) throw new Error(`POST failed with ${posted.status}`);
      const { task_id: taskId } = (await posted.json()) as { task_id: string };
      let detail: {
        task: { status: string };
        invocations: Array<{ depth: number; status: string; result_text: string | null }>;
      };
      do {
        await sleep(250);
        detail = await (await fetch(`${base}/api/tasks/${taskId}`, { headers })).json();
      } while (detail.task.status === "running" && performance.now() - started < taskTimeoutMs);
      const latencyMs = Math.round(performance.now() - started);
      await sleep(300); // usage rows are written after the final model turn resolves
      const usage = await database.query<{
        calls: string;
        input: string | null;
        output: string | null;
        cost: string | null;
      }>(
        `SELECT count(*) AS calls, sum(input_tokens) AS input, sum(output_tokens) AS output,
                sum(estimated_cost) AS cost
         FROM platform_usage_records WHERE kind = 'model' AND created_at >= $1`,
        [since],
      );
      const row = usage.rows[0];
      const costUsd = Number(row?.cost ?? 0);
      spent += costUsd;
      const root = detail.invocations.find(({ depth }) => depth === 0);
      const answer = root?.result_text ?? "";
      const delegations = detail.invocations.filter(({ depth }) => depth > 0).length;
      samples.push({
        scenario: scenario.id,
        iteration,
        taskStatus: detail.task.status,
        latencyMs,
        invocations: detail.invocations.length,
        delegations,
        modelCalls: Number(row?.calls ?? 0),
        inputTokens: Number(row?.input ?? 0),
        outputTokens: Number(row?.output ?? 0),
        costUsd: Number(costUsd.toFixed(8)),
        checks: checks(scenario.id, answer, delegations),
        answerPreview: answer.replace(/\s+/g, " ").slice(0, 240),
      });
      console.log(
        `${scenario.id}#${iteration} ${detail.task.status} ${latencyMs}ms $${costUsd.toFixed(5)}`,
      );
    }
  }

  const summary = SCENARIOS.map(({ id }) => {
    const runs = samples.filter((sample) => sample.scenario === id);
    const latencies = runs.map(({ latencyMs }) => latencyMs);
    const passed = runs.filter(
      (run) => run.taskStatus === "completed" && Object.values(run.checks).every(Boolean),
    ).length;
    const mean = (pick: (sample: Sample) => number) =>
      runs.length ? Math.round(runs.reduce((total, run) => total + pick(run), 0) / runs.length) : 0;
    return {
      scenario: id,
      runs: runs.length,
      passed,
      latencyMs: { p50: percentile(latencies, 50), p95: percentile(latencies, 95) },
      meanModelCalls: mean(({ modelCalls }) => modelCalls),
      meanInputTokens: mean(({ inputTokens }) => inputTokens),
      meanOutputTokens: mean(({ outputTokens }) => outputTokens),
      costUsd: Number(runs.reduce((total, run) => total + run.costUsd, 0).toFixed(6)),
    };
  });
  const models = await database.query<{ provider: string; model: string }>(
    "SELECT DISTINCT provider, model FROM platform_usage_records WHERE kind = 'model'",
  );
  const receipt = {
    kind: "e2e-benchmark",
    createdAt: new Date().toISOString(),
    topology: "API server + separate durable worker (PLATFORM_RUNNER_MODE=api), web API path",
    database: `disposable ${IMAGE}`,
    models: models.rows,
    budgetUsd,
    spentUsd: Number(spent.toFixed(6)),
    repeat,
    summary,
    skipped,
    samples,
    limitations: [
      "Single machine, sequential scenarios, small sample: p95 of 3 runs is the max, not a tail estimate.",
      "Warehouse is the synthetic mock provider; latency excludes a real warehouse.",
      "Cost is provider-reported usage.cost via pi-ai, attributed by time window per sequential scenario.",
    ],
  };
  mkdirSync("docs/execution/live", { recursive: true });
  const path = `docs/execution/live/e2e-benchmark-${receipt.createdAt.replace(/[:.]/g, "-")}.json`;
  const raw = `${JSON.stringify(receipt, null, 2)}\n`;
  const formatted = spawnSync("pnpm", ["exec", "biome", "format", "--stdin-file-path", path], {
    input: raw,
    encoding: "utf8",
  });
  writeFileSync(path, formatted.status === 0 ? formatted.stdout : raw);
  console.log(JSON.stringify({ path, spentUsd: receipt.spentUsd, summary }, null, 2));
} catch (failure) {
  console.error(failure instanceof Error ? failure.message : failure);
  console.error(log.slice(-40).join("\n"));
  process.exitCode = 1;
} finally {
  await database?.end().catch(() => undefined);
  for (const child of children) child.kill("SIGTERM");
  await sleep(1_000);
  for (const child of children) if (child.exitCode === null) child.kill("SIGKILL");
  docker(["rm", "--force", "--volumes", name]);
}
