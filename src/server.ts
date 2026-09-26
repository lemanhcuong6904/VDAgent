import { serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";
import { bodyLimit } from "hono/body-limit";
import { Pool } from "pg";
import { Value } from "typebox/value";
import { assertSecureSecret, isAuthorizedAgent } from "./agent-auth.js";
import { migrateDatabase } from "./database.js";
import { handleMcpRequest } from "./mcp-server.js";
import { newTraceContext } from "./observability.js";
import { OutboxPublisher } from "./outbox.js";
import { loadPlatformServices } from "./platform-services.js";
import { RunLedger } from "./run-ledger.js";
import { DurableRunWorker } from "./run-worker.js";
import { createWebTaskRunExecutor, reconcileInterruptedTasks, registerWebApi } from "./web-api.js";
import { createWebAuth } from "./web-auth.js";

const token = process.env.API_TOKEN;
if (!token) throw new Error("API_TOKEN is required");
const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error("DATABASE_URL is required");
const webAuth = createWebAuth();
const requireSecureSecrets =
  process.env.PLATFORM_REQUIRE_SECURE_SECRETS === "true" || process.env.NODE_ENV === "production";
if (requireSecureSecrets) assertSecureSecret("API_TOKEN", token);

const database = new Pool({ connectionString: databaseUrl, max: 20 });
database.on("error", (error) => {
  process.stderr.write(`PostgreSQL pool error: ${error.message}\n`);
});
await migrateDatabase(database);
const runnerMode = process.env.PLATFORM_RUNNER_MODE ?? "embedded";
if (!["embedded", "api", "legacy"].includes(runnerMode)) {
  throw new Error("PLATFORM_RUNNER_MODE must be embedded, api, or legacy");
}
const services = await loadPlatformServices(database);
const { pool, runtime, pluginRegistry, catalog } = services;
if (requireSecureSecrets) {
  for (const agent of pluginRegistry.list()) {
    const key = `AGENT_TOKEN_${agent.id.toUpperCase().replace(/[^A-Z0-9]/g, "_")}`;
    assertSecureSecret(key, process.env[key]);
  }
}
const runLedger = runnerMode === "legacy" ? undefined : new RunLedger(database);
if (runnerMode === "legacy") {
  await reconcileInterruptedTasks(database);
}

const app = new Hono();
app.use("*", bodyLimit({ maxSize: 1_000_000 }));
app.get("/health", (context) => context.json({ status: "ok" }));
registerWebApi(app, {
  database,
  pluginRegistry,
  pool,
  runtime,
  catalog,
  runLedger,
  webAuth,
});

app.use("/v1/*", async (context, next) => {
  if (context.req.header("authorization") !== `Bearer ${token}`) {
    return context.json({ error: "unauthorized" }, 401);
  }
  await next();
});

app.get("/v1/agents", (context) => context.json(pluginRegistry.list()));
app.get("/v1/tools", (context) => {
  const agentId = context.req.header("x-agent-id") ?? "";
  const agent = pluginRegistry.get(agentId);
  if (!agent) return context.json({ error: "unknown agent" }, 404);
  return context.json(
    pool
      .forAgent(agentId)
      .filter(({ name }) => agent.descriptor.tools.includes(name))
      .map(({ name, description, schema }) => ({
        name,
        description,
        inputSchema: schema,
      })),
  );
});
app.post("/v1/agents/:agentId/run", async (context) => {
  const body = await context.req.json().catch(() => undefined);
  if (!body || typeof body !== "object" || !("input" in body)) {
    return context.json({ error: "input is required" }, 422);
  }
  const suppliedSessionId = "sessionId" in body ? body.sessionId : undefined;
  if (
    suppliedSessionId !== undefined &&
    (typeof suppliedSessionId !== "string" || !/^[a-zA-Z0-9._:-]{1,128}$/.test(suppliedSessionId))
  ) {
    return context.json({ error: "sessionId must be 1-128 safe characters" }, 422);
  }
  const plugin = pluginRegistry.get(context.req.param("agentId"));
  if (!plugin) return context.json({ error: "unknown agent" }, 404);
  if (!Value.Check(plugin.descriptor.input, body.input)) {
    return context.json({ error: "input does not match the agent schema" }, 422);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("run timeout"), 180_000);
  const cancelOnDisconnect = () => controller.abort("client disconnected");
  context.req.raw.signal.addEventListener("abort", cancelOnDisconnect, { once: true });
  if (context.req.raw.signal.aborted) cancelOnDisconnect();
  try {
    const result = await plugin.run(body.input, {
      runId: crypto.randomUUID(),
      sessionId: typeof suppliedSessionId === "string" ? suppliedSessionId : crypto.randomUUID(),
      userId: process.env.API_USER_ID ?? "local-user",
      spaceId: process.env.API_SPACE_ID ?? "local-space",
      signal: controller.signal,
      tools: pool.forNames(plugin.descriptor.tools),
      runtime,
      catalog: pluginRegistry.plannerCatalog(),
      trace: newTraceContext(),
      pool,
    });
    if (plugin.descriptor.output && !Value.Check(plugin.descriptor.output, result)) {
      return context.json({ error: "agent output does not match its schema" }, 500);
    }
    return context.json(result);
  } catch (error) {
    if (error instanceof Error && error.name === "PiSessionBusyError") {
      return context.json({ error: error.message }, 409);
    }
    return context.json({ error: error instanceof Error ? error.message : "analysis failed" }, 500);
  } finally {
    clearTimeout(timer);
    context.req.raw.signal.removeEventListener("abort", cancelOnDisconnect);
  }
});

app.all("/mcp", async (context) => {
  const agentId = context.req.header("x-agent-id") ?? "";
  if (
    !isAuthorizedAgent(
      agentId,
      context.req.header("authorization"),
      process.env,
      (id) => !!pluginRegistry.get(id),
    )
  ) {
    return context.json({ error: "unauthorized" }, 401);
  }
  return handleMcpRequest(context.req.raw, {
    agentId,
    userId: process.env.API_USER_ID ?? "local-user",
    spaceId: process.env.API_SPACE_ID ?? "local-space",
    allowedTools: pluginRegistry.get(agentId)?.descriptor.tools ?? [],
    pool,
  });
});

app.get("*", serveStatic({ root: "./frontend/dist" }));

const port = Number(process.env.PORT ?? 3000);
let worker: DurableRunWorker | undefined;
let outbox: OutboxPublisher | undefined;
if (runnerMode === "embedded" && runLedger) {
  worker = new DurableRunWorker(
    runLedger,
    createWebTaskRunExecutor({ database, pluginRegistry, pool, runtime, catalog }),
    {
      workerId: process.env.WORKER_ID || `embedded-${process.pid}`,
      leaseMs: positiveInt(process.env.WORKER_LEASE_MS, 30_000),
      pollMs: positiveInt(process.env.WORKER_POLL_MS, 250),
      concurrency: positiveInt(process.env.WORKER_CONCURRENCY, 4),
    },
  );
  outbox = new OutboxPublisher(
    database,
    async (event) => {
      process.stdout.write(
        `${JSON.stringify({ message: "platform.outbox_published", outbox_id: event.id, run_id: event.run_id, event_type: event.event_type })}\n`,
      );
    },
    { publisherId: `outbox-${process.pid}`, pollMs: positiveInt(process.env.OUTBOX_POLL_MS, 250) },
  );
  outbox.start();
  worker.start();
}
serve({ fetch: app.fetch, port, hostname: "0.0.0.0" }, (info) => {
  process.stdout.write(`Team 6 cAi API listening on ${info.port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    void outbox
      ?.stop()
      .finally(() => worker?.stop())
      .finally(() => database.end());
  });
}

export { app };

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
