import { serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";
import { Pool } from "pg";
import { Value } from "typebox/value";
import { parseA2aClients, registerA2aGateway } from "./a2a-gateway.js";
import { assertSecureSecret, isAuthorizedAgent } from "./agent-auth.js";
import { recordAudit } from "./audit.js";
import { migrateDatabase, migrationStatus } from "./database.js";
import { applyHttpSecurity } from "./http-security.js";
import { Lifecycle } from "./lifecycle.js";
import { ParticipatingRunReader } from "./mcp-run-reader.js";
import { handleMcpRequest } from "./mcp-server.js";
import { renderPrometheus } from "./metrics.js";
import { newTraceContext } from "./observability.js";
import { OutboxPublisher } from "./outbox.js";
import { createOutboxFanout } from "./outbox-consumers.js";
import { registerLegacyAdapter, registerPlatformApi } from "./platform-api.js";
import { loadPlatformServices } from "./platform-services.js";
import { clientAddress, RateLimiter, requestKey } from "./rate-limit.js";
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
await migrateDatabase(database, {
  lockTimeoutMs: positiveInt(process.env.MIGRATION_LOCK_TIMEOUT_MS, 120_000),
});
const lifecycle = new Lifecycle({
  ping: () => database.query("SELECT 1"),
  migrations: () => migrationStatus(database),
});
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
applyHttpSecurity(app, {
  allowedOrigin: process.env.WEB_ALLOWED_ORIGIN ?? "http://localhost:3000",
});
const limiter = new RateLimiter({
  maxRequests: positiveInt(process.env.RATE_LIMIT_REQUESTS_PER_MINUTE, 120),
  windowMs: 60_000,
});
app.use("*", async (context, next) => {
  const path = context.req.path;
  if (path === "/health" || path === "/live" || path === "/ready" || path === "/metrics")
    return next();
  const remoteAddress = (
    context.env as { incoming?: { socket?: { remoteAddress?: string } } } | undefined
  )?.incoming?.socket?.remoteAddress;
  const ip = clientAddress({
    remoteAddress,
    forwardedFor: context.req.header("x-forwarded-for"),
    trustProxy: process.env.TRUST_PROXY === "true",
  });
  if (!limiter.allow(requestKey({ ip, route: path }))) {
    await recordAudit(database, {
      actor: ip,
      action: "rate_limit",
      resourceType: "http",
      resourceId: path,
      outcome: "denied",
    }).catch(() => undefined);
    return context.json({ error: { code: "rate_limited", message: "Too many requests" } }, 429);
  }
  await next();
});
// Liveness never touches dependencies; readiness does (M13.1).
const live = (context: import("hono").Context) =>
  context.json({ status: "ok", phase: lifecycle.phase });
app.get("/health", live);
app.get("/live", live);
app.get("/ready", async (context) => {
  const report = await lifecycle.readiness();
  return context.json(
    { status: report.ready ? "ready" : "not_ready", ...report },
    report.ready ? 200 : 503,
  );
});
app.get("/metrics", (context) =>
  context.text(renderPrometheus(), 200, { "content-type": "text/plain; version=0.0.4" }),
);
// Adapter first: its middleware must wrap the legacy routes registered next (M12.2).
registerLegacyAdapter(app, { database, pluginRegistry, webAuth, runLedger });
registerWebApi(app, {
  database,
  pluginRegistry,
  pool,
  runtime,
  catalog,
  runLedger,
  webAuth,
});

// Versioned surface (M12.1). Mounted after the legacy projection so both can be
// compared while the UI migrates; removing this one call is the rollback.
registerPlatformApi(app, {
  database,
  pluginRegistry,
  webAuth,
  runLedger,
  spaceId: process.env.API_SPACE_ID ?? "local-space",
});

app.use("/v1/*", async (context, next) => {
  if (context.req.header("authorization") !== `Bearer ${token}`) {
    await recordAudit(database, {
      actor: "anonymous",
      action: "operator_auth",
      resourceType: "http",
      resourceId: context.req.path,
      outcome: "denied",
    }).catch(() => undefined);
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

// An agent may read a run over MCP only if it ran a step in it (M12.4).
const mcpRuns = new ParticipatingRunReader(database);

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
    await recordAudit(database, {
      actor: agentId || "anonymous",
      action: "mcp_auth",
      resourceType: "agent",
      resourceId: agentId,
      outcome: "denied",
    }).catch(() => undefined);
    return context.json(
      { error: { code: "unauthorized", message: "Agent id and token do not match" } },
      401,
    );
  }
  return handleMcpRequest(context.req.raw, {
    agentId,
    userId: process.env.API_USER_ID ?? "local-user",
    spaceId: process.env.API_SPACE_ID ?? "local-space",
    allowedTools: pluginRegistry.get(agentId)?.descriptor.tools ?? [],
    pool,
    descriptor: pluginRegistry.list().find((agent) => agent.id === agentId),
    runs: mcpRuns,
    maxResultBytes: positiveInt(process.env.MCP_MAX_RESULT_BYTES, 256_000),
    allowedOrigins: (process.env.MCP_ALLOWED_ORIGINS ?? "")
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean),
  });
});

// Optional A2A gateway (M12.5). Off unless explicitly enabled; unsetting the flag is
// the rollback and leaves both routes unmounted (they fall through to 404 / the SPA).
if (process.env.A2A_ENABLED === "true") {
  if (!runLedger) throw new Error("A2A_ENABLED requires the durable run ledger");
  const a2aClients = parseA2aClients(process.env.A2A_CLIENTS);
  if (a2aClients.length === 0)
    throw new Error("A2A_ENABLED requires at least one A2A_CLIENTS entry");
  registerA2aGateway(app, {
    database,
    pluginRegistry,
    runLedger,
    clients: a2aClients,
    publicUrl: process.env.A2A_PUBLIC_URL ?? `http://localhost:${process.env.PORT ?? 3000}`,
  });
}

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
  const outboxFanout = createOutboxFanout();
  outbox = new OutboxPublisher(database, outboxFanout.dispatch, {
    publisherId: `outbox-${process.pid}`,
    pollMs: positiveInt(process.env.OUTBOX_POLL_MS, 250),
  });
  outbox.start();
  worker.start();
}
const httpServer = serve({ fetch: app.fetch, port, hostname: "0.0.0.0" }, (info) => {
  lifecycle.markReady();
  process.stdout.write(`Team 6 cAi API listening on ${info.port}\n`);
});

// Order matters: leave rotation, stop accepting HTTP, let in-flight runs finish,
// then stop the outbox and close the pool last because every earlier step uses it.
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    void lifecycle
      .shutdown(
        [
          {
            name: "http",
            run: () =>
              closeHttpServer(httpServer, positiveInt(process.env.HTTP_CLOSE_GRACE_MS, 5_000)),
          },
          {
            name: "worker",
            run: async () => worker?.drain(positiveInt(process.env.WORKER_DRAIN_GRACE_MS, 20_000)),
          },
          { name: "outbox", run: async () => outbox?.stop() },
          { name: "tracing", run: () => services.shutdownTracing() },
          { name: "memory-retention", run: () => services.shutdownMemoryRetention() },
          { name: "warehouse-database", run: () => services.shutdownWarehouse() },
          { name: "database", run: () => database.end() },
        ],
        {
          drainDelayMs: positiveInt(process.env.SHUTDOWN_DRAIN_DELAY_MS, 5_000),
          timeoutMs: positiveInt(process.env.SHUTDOWN_TIMEOUT_MS, 30_000),
        },
      )
      .then((result) => {
        process.stdout.write(`${JSON.stringify({ message: "platform.shutdown", ...result })}\n`);
        process.exit(result.ok ? 0 : 1);
      });
  });
}

export { app };

/**
 * Stop accepting connections, then cut the ones still open after `graceMs`. SSE
 * streams (`/api/events`, run and A2A streams) never end by themselves; clients
 * reconnect with their cursor, so cutting them loses nothing.
 */
function closeHttpServer(server: ReturnType<typeof serve>, graceMs: number): Promise<void> {
  const http = server as unknown as {
    close(callback: () => void): void;
    closeIdleConnections?: () => void;
    closeAllConnections?: () => void;
  };
  return new Promise<void>((resolve) => {
    const timer = setTimeout(() => http.closeAllConnections?.(), graceMs);
    http.close(() => {
      clearTimeout(timer);
      resolve();
    });
    http.closeIdleConnections?.();
  });
}

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
