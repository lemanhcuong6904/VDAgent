/**
 * Runs the Python reference roster (agents/manifests) without Postgres: real warehouse tools over
 * the mock provider, an in-memory artifact store, and an in-process `agents.delegate` that spawns
 * each specialist exactly like production does. The runtime is injected (fake or real PiRuntime).
 */
import { randomBytes, randomUUID } from "node:crypto";
import { Type } from "typebox";
import type { AgentRuntime } from "../../src/agent-contract.js";
import { DEFAULT_AGENT_MANIFESTS } from "../../src/platform-services.js";
import { warehouse } from "../../src/providers/warehouse/mock.js";
import { AgentPool, loadExternalAgentPlugins } from "../../src/registry.js";
import { McpToolPool, type ToolScope } from "../../src/tool-pool.js";
import { createAgentCatalogTool } from "../../src/tools/agent-catalog.js";
import {
  createWarehouseTools,
  type WarehouseColumn,
  WarehouseRegistry,
} from "../../src/warehouse.js";
import type { PostgresWarehouseArtifacts } from "../../src/warehouse-artifacts.js";

type Row = Record<string, unknown>;
const artifactId = (prefix: string) =>
  `${prefix}_${randomBytes(9).toString("base64url").replace(/[-_]/g, "a").slice(0, 12)}`;

export class MemoryArtifacts {
  readonly datasets = new Map<
    string,
    { id: string; name: string; columns: WarehouseColumn[]; rows: Row[] }
  >();
  readonly charts = new Map<string, { id: string; datasetId: string; title: string; spec: Row }>();
  readonly reports = new Map<string, { id: string; title: string; markdown: string }>();

  async saveDataset(input: { name: string; columns: WarehouseColumn[]; rows: Row[] }) {
    const id = artifactId("ds");
    this.datasets.set(id, { id, name: input.name, columns: input.columns, rows: input.rows });
    return { id, row_count: input.rows.length };
  }

  async getDataset(id: string) {
    return this.datasets.get(id);
  }

  async saveChart(input: { datasetId: string; title: string; spec: Row }) {
    if (!this.datasets.has(input.datasetId)) throw new Error("Dataset not found");
    const id = artifactId("ch");
    this.charts.set(id, { id, ...input });
    return { id, embed: `{{chart:${id}}}` };
  }

  async saveReport(input: { title: string; markdown: string }) {
    const id = artifactId("rp");
    this.reports.set(id, { id, ...input });
    return { id };
  }
}

export interface Invocation {
  agent: string;
  status: "completed" | "failed";
  output: string;
}

export async function createPythonRoster(runtime: AgentRuntime) {
  const agents = new AgentPool();
  for (const plugin of await loadExternalAgentPlugins(DEFAULT_AGENT_MANIFESTS))
    agents.register(plugin);
  const registry = new WarehouseRegistry();
  registry.register(warehouse);
  const artifacts = new MemoryArtifacts();
  const pool = new McpToolPool();
  for (const tool of createWarehouseTools(
    registry,
    artifacts as unknown as PostgresWarehouseArtifacts,
  ))
    pool.register(tool);
  pool.register(createAgentCatalogTool(agents));
  const invocations: Invocation[] = [];

  const runChild = async (agentId: string, message: string, scope: ToolScope) => {
    const plugin = agents.get(agentId);
    if (!plugin || plugin.descriptor.acceptsDelegation === false)
      throw new Error(`Unknown agent '${agentId}'`);
    try {
      const output = await plugin.run(
        { prompt: message },
        {
          runId: `inv_${randomUUID().slice(0, 12)}`,
          sessionId: `test:${agentId}`,
          userId: scope.userId,
          spaceId: scope.spaceId,
          taskId: scope.taskId,
          depth: 1,
          signal: scope.signal,
          tools: pool.forNames(plugin.descriptor.tools),
          runtime,
          modelProfile: plugin.descriptor.modelProfile,
          pool,
        },
      );
      const text = typeof output === "string" ? output : JSON.stringify(output);
      invocations.push({ agent: agentId, status: "completed", output: text });
      return text;
    } catch (error) {
      const text = `error: ${error instanceof Error ? error.message : String(error)}`;
      invocations.push({ agent: agentId, status: "failed", output: text });
      return text;
    }
  };

  pool.register({
    name: "agents.delegate",
    description: "In-process delegation for tests.",
    schema: Type.Object({
      agent: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      capability: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      message: Type.String({ minLength: 1, maxLength: 4000 }),
    }),
    mutates: true,
    timeoutMs: 120_000,
    agents: ["orchestrator"],
    authorize: () => true,
    async execute(raw, scope) {
      const input = raw as { agent?: string; capability?: string; message: string };
      const target =
        input.agent ?? agents.findByCapability(input.capability ?? "")[0]?.descriptor.id;
      if (!target) throw new Error("No agent matches the delegation");
      return runChild(target, input.message, scope);
    },
  });

  async function ask(prompt: string, signal = AbortSignal.timeout(280_000)) {
    const orchestrator = agents.get("orchestrator");
    if (!orchestrator) throw new Error("orchestrator is not registered");
    const output = await orchestrator.run(
      { prompt },
      {
        runId: `inv_${randomUUID().slice(0, 12)}`,
        sessionId: "test:orchestrator",
        userId: "user-python-roster",
        spaceId: "space-python-roster",
        taskId: `task_${randomUUID().slice(0, 12)}`,
        depth: 0,
        signal,
        tools: pool.forNames(orchestrator.descriptor.tools),
        runtime,
        modelProfile: orchestrator.descriptor.modelProfile,
        pool,
      },
    );
    return typeof output === "string" ? output : JSON.stringify(output);
  }

  return { agents, pool, artifacts, invocations, ask, runChild };
}
