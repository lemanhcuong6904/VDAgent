import { Pool } from "pg";
import { ArtifactStorage } from "./artifact-storage.js";
import { DockerSandboxProvider } from "./docker-sandbox.js";
import { EvidenceStorage } from "./evidence-storage.js";
import { createAgentMemoryTools } from "./memory-store.js";
import { createDefaultModelRegistry } from "./model-registry.js";
import { createTelemetry, type Telemetry } from "./observability.js";
import { startTracing } from "./otel-tracing.js";
import { PiRuntime } from "./pi-runtime.js";
import {
  PostgresAgentMemoryProvider,
  PostgresMemoryAuditWriter,
  PostgresPiSessionStore,
} from "./postgres-store.js";
import { PolicyEngine } from "./registry/policy-engine.js";
import { type AgentPool, loadAgentPool, loadExternalAgentPlugins } from "./registry.js";
import { RunLedger } from "./run-ledger.js";
import { runtimeModuleSpecifier } from "./runtime-module-path.js";
import { createSandboxTool, selectSandboxProvider } from "./sandbox.js";
import { SandboxSupervisor } from "./sandbox-supervisor.js";
import { loadToolPool, type McpToolPool } from "./tool-pool.js";
import { createAgentCatalogTool } from "./tools/agent-catalog.js";
import { createAgentCommunicationTools } from "./tools/agent-communication.js";
import { createAgentDelegationTool } from "./tools/agent-delegation.js";
import { createArtifactTools } from "./tools/artifacts.js";

/** Reference Python agents (agent-runner.v2); override with AGENT_EXTERNAL_MANIFESTS. */
export const DEFAULT_AGENT_MANIFESTS = [
  "orchestrator",
  "data",
  "compare",
  "insight",
  "visualize",
  "report",
].map((id) => `agents/manifests/${id}.json`);

export interface PlatformServices {
  telemetry?: Telemetry;
  pool: McpToolPool;
  runtime: PiRuntime;
  pluginRegistry: AgentPool;
  catalog: ReturnType<AgentPool["plannerCatalog"]>;
  runLedger: RunLedger;
  /** Flushes and stops the OTLP exporter when tracing is configured; else a no-op. */
  shutdownTracing: () => Promise<void>;
  shutdownWarehouse: () => Promise<void>;
  shutdownMemoryRetention: () => Promise<void>;
}

export async function loadPlatformServices(database: Pool): Promise<PlatformServices> {
  // OTEL_EXPORTER_OTLP_*/LANGFUSE_HOST configured: export real OTel traces (Langfuse-compatible).
  // Otherwise fall back to the existing JSON/Prometheus telemetry.
  const tracing = startTracing();
  const telemetry = tracing?.telemetry ?? createTelemetry();
  const shutdownTracing = tracing ? tracing.shutdown : async () => {};
  const warehouseUrl = process.env.WAREHOUSE_DATABASE_URL;
  const warehouseDatabase = warehouseUrl
    ? new Pool({ connectionString: warehouseUrl, max: 10 })
    : undefined;
  warehouseDatabase?.on("error", (error) => {
    process.stderr.write(`Warehouse PostgreSQL pool error: ${error.message}\n`);
  });
  const shutdownWarehouse = async () => {
    await warehouseDatabase?.end();
  };
  const moduleList = (key: string) =>
    (process.env[key] ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);

  const toolModules = moduleList("AGENT_TOOL_MODULES");
  const pool = await loadToolPool(
    (toolModules.length ? toolModules : ["src/tools/warehouse.ts"]).map((specifier) =>
      runtimeModuleSpecifier(specifier),
    ),
    { database, warehouseDatabase, telemetry },
  );
  const agentMemory = new PostgresAgentMemoryProvider(database);
  for (const tool of createAgentMemoryTools(agentMemory)) {
    pool.register(tool);
  }
  for (const tool of createArtifactTools(new ArtifactStorage(database))) pool.register(tool);

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
  const evidence = new EvidenceStorage(database, {
    requireArtifactVerification: true,
  });
  const memoryAudit = new PostgresMemoryAuditWriter(database, {
    retentionDays: positiveInt(process.env.MEMORY_AUDIT_RETENTION_DAYS, 365),
  });
  const sweepMemoryRetention = async () => {
    const results = await Promise.allSettled([
      agentMemory.purgeExpired(),
      memoryAudit.purgeExpired(),
    ]);
    for (const result of results) {
      if (result.status === "rejected") {
        process.stderr.write(
          `${JSON.stringify({ message: "memory.retention_sweep_failed", error: result.reason instanceof Error ? result.reason.message : "unknown" })}\n`,
        );
      }
    }
  };
  await sweepMemoryRetention();
  // Start the recurring sweep only after every plugin has loaded successfully.
  // A failed plugin load must not leave a live timer holding the process open.
  let memoryRetentionTimer: ReturnType<typeof setInterval> | undefined;
  const shutdownMemoryRetention = async () => {
    if (!memoryRetentionTimer) return;
    clearInterval(memoryRetentionTimer);
    memoryRetentionTimer = undefined;
  };
  // Real capability/tool grant checks for external agents (M3); grants are
  // self-seeded per manifest so existing access is preserved by default.
  const policy = new PolicyEngine();
  const runtime = new PiRuntime(
    new PostgresPiSessionStore(database),
    createDefaultModelRegistry(),
    telemetry,
    (record) => runLedger.recordUsage({ ...record, kind: "model" }),
  );
  // In-process TS modules are opt-in; the default roster is the Python agents under agents/.
  const pluginRegistry = await loadAgentPool(
    moduleList("AGENT_PLUGIN_MODULES").map((specifier) => runtimeModuleSpecifier(specifier)),
    { memoryAudit },
  );
  const externalModules = moduleList("AGENT_EXTERNAL_MANIFESTS");
  for (const plugin of await loadExternalAgentPlugins(
    externalModules.length ? externalModules : DEFAULT_AGENT_MANIFESTS,
    { evidence, policy, memoryAudit },
  )) {
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
  memoryRetentionTimer = setInterval(
    () => void sweepMemoryRetention(),
    Math.min(
      Math.max(positiveInt(process.env.MEMORY_RETENTION_SWEEP_MS, 3_600_000), 60_000),
      86_400_000,
    ),
  );
  memoryRetentionTimer.unref();
  return {
    telemetry,
    pool,
    runtime,
    pluginRegistry,
    catalog,
    runLedger,
    shutdownTracing,
    shutdownWarehouse,
    shutdownMemoryRetention,
  };
}

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
