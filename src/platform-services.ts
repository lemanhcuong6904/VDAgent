import type { Pool } from "pg";
import { DockerSandboxProvider } from "./docker-sandbox.js";
import { createAgentMemoryTools } from "./memory-store.js";
import { createDefaultModelRegistry } from "./model-registry.js";
import { createTelemetry, type Telemetry } from "./observability.js";
import { PiRuntime } from "./pi-runtime.js";
import { PostgresAgentMemoryProvider, PostgresPiSessionStore } from "./postgres-store.js";
import { type AgentPool, loadAgentPool, loadExternalAgentPlugins } from "./registry.js";
import { RunLedger } from "./run-ledger.js";
import { createSandboxTool, selectSandboxProvider } from "./sandbox.js";
import { SandboxSupervisor } from "./sandbox-supervisor.js";
import { loadToolPool, type McpToolPool } from "./tool-pool.js";
import { createAgentCatalogTool } from "./tools/agent-catalog.js";
import { createAgentCommunicationTools } from "./tools/agent-communication.js";
import { createAgentDelegationTool } from "./tools/agent-delegation.js";

export interface PlatformServices {
  telemetry?: Telemetry;
  pool: McpToolPool;
  runtime: PiRuntime;
  pluginRegistry: AgentPool;
  catalog: ReturnType<AgentPool["plannerCatalog"]>;
  runLedger: RunLedger;
}

export async function loadPlatformServices(database: Pool): Promise<PlatformServices> {
  const telemetry = createTelemetry();
  const moduleList = (key: string) =>
    (process.env[key] ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);

  const toolModules = moduleList("AGENT_TOOL_MODULES");
  const pool = await loadToolPool(toolModules.length ? toolModules : ["src/tools/warehouse.ts"], {
    database,
    telemetry,
  });
  for (const tool of createAgentMemoryTools(new PostgresAgentMemoryProvider(database))) {
    pool.register(tool);
  }

  const sandboxProviderId = process.env.SANDBOX_PROVIDER ?? "docker";
  const sandboxProvider = selectSandboxProvider(sandboxProviderId, new DockerSandboxProvider());
  if (sandboxProvider)
    pool.register(
      createSandboxTool(
        new SandboxSupervisor(sandboxProvider, {
          maxConcurrentPerAgent: positiveInt(process.env.SANDBOX_MAX_CONCURRENT, 2),
          maxCommandTimeoutMs: positiveInt(process.env.SANDBOX_MAX_TIMEOUT_MS, 300_000),
        }),
      ),
    );

  const runLedger = new RunLedger(database);
  const runtime = new PiRuntime(
    new PostgresPiSessionStore(database),
    createDefaultModelRegistry(),
    telemetry,
    (record) => runLedger.recordUsage({ ...record, kind: "model" }),
  );
  const pluginModules = moduleList("AGENT_PLUGIN_MODULES");
  const pluginRegistry = await loadAgentPool(
    pluginModules.length ? pluginModules : ["src/agents/index.ts"],
  );
  const externalModules = moduleList("AGENT_EXTERNAL_MANIFESTS");
  for (const plugin of await loadExternalAgentPlugins(externalModules)) {
    pluginRegistry.register(plugin);
  }
  for (const agent of pluginRegistry.list()) {
    pool.registerAgentManifest(agent.id, agent.tools);
  }
  const catalog = pluginRegistry.plannerCatalog();
  pool.register(createAgentCatalogTool(pluginRegistry));
  pool.register(
    createAgentDelegationTool({
      database,
      pluginRegistry,
      pool,
      runtime,
      catalog,
    }),
  );
  for (const tool of createAgentCommunicationTools({ database, runLedger, pluginRegistry })) {
    pool.register(tool);
  }
  return { telemetry, pool, runtime, pluginRegistry, catalog, runLedger };
}

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
