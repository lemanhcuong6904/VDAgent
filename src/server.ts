import { serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";
import { Pool } from "pg";
import { Value } from "typebox/value";
import { isAuthorizedAgent } from "./agent-auth.js";
import { migrateDatabase } from "./database.js";
import { DockerSandboxProvider } from "./docker-sandbox.js";
import { handleMcpRequest } from "./mcp-server.js";
import { createAgentMemoryTools } from "./memory-store.js";
import { PiRuntime } from "./pi-runtime.js";
import { PostgresAgentMemoryProvider, PostgresPiSessionStore } from "./postgres-store.js";
import { loadAgentPool } from "./registry.js";
import { createSandboxTool, selectSandboxProvider } from "./sandbox.js";
import { loadToolPool } from "./tool-pool.js";
import { createAgentDelegationTool } from "./tools/agent-delegation.js";
import { registerWebApi } from "./web-api.js";

const token = process.env.API_TOKEN;
if (!token) throw new Error("API_TOKEN is required");
const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error("DATABASE_URL is required");

const database = new Pool({ connectionString: databaseUrl, max: 20 });
database.on("error", (error) => {
  process.stderr.write(`PostgreSQL pool error: ${error.message}\n`);
});
await migrateDatabase(database);

const moduleList = (key: string) =>
  (process.env[key] ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

const toolModules = moduleList("AGENT_TOOL_MODULES");
const pool = await loadToolPool(toolModules.length ? toolModules : ["src/tools/warehouse.ts"], {
  database,
});
for (const tool of createAgentMemoryTools(new PostgresAgentMemoryProvider(database))) {
  pool.register(tool);
}
const sandboxProviderId = process.env.SANDBOX_PROVIDER ?? "docker";
const sandboxProvider = selectSandboxProvider(sandboxProviderId, new DockerSandboxProvider());
if (sandboxProvider) pool.register(createSandboxTool(sandboxProvider));
const runtime = new PiRuntime(new PostgresPiSessionStore(database));
const pluginModules = moduleList("AGENT_PLUGIN_MODULES");
const pluginRegistry = await loadAgentPool(
  pluginModules.length ? pluginModules : ["src/agents/index.ts"],
);
pool.register(createAgentDelegationTool({ database, pluginRegistry, pool, runtime }));

const app = new Hono();
app.get("/health", (context) => context.json({ status: "ok" }));
registerWebApi(app, { database, pluginRegistry, pool, runtime });

app.use("/v1/*", async (context, next) => {
  if (context.req.header("authorization") !== `Bearer ${token}`) {
    return context.json({ error: "unauthorized" }, 401);
  }
  await next();
});

app.get("/v1/agents", (context) => context.json(pluginRegistry.list()));
app.get("/v1/tools", (context) => {
  const agentId = context.req.header("x-agent-id") ?? "";
  return context.json(
    pool.forAgent(agentId).map(({ name, description, schema }) => ({
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
    pool,
  });
});

app.get("*", serveStatic({ root: "./frontend/dist" }));

const port = Number(process.env.PORT ?? 3000);
serve({ fetch: app.fetch, port, hostname: "0.0.0.0" }, (info) => {
  process.stdout.write(`Team 6 cAi API listening on ${info.port}\n`);
});

export { app };
