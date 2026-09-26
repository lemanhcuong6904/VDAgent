import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { TSchema } from "typebox";
import type { AgentPlugin } from "./agent-contract.js";
import { JsonLineAgentRunner } from "./agent-runner.js";
import type { PlannerAgent, PlannerCatalog } from "./planner.js";

export class AgentPool {
  private readonly plugins = new Map<string, AgentPlugin>();

  register(plugin: AgentPlugin): void {
    validateAgentPlugin(plugin);
    const { id, version, input, tools } = plugin.descriptor;
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(id)) throw new Error(`Invalid agent id '${id}'`);
    if (!version.trim()) throw new Error(`Agent '${id}' must have a version`);
    if (this.plugins.has(id)) throw new Error(`Agent '${id}' is already registered`);
    this.plugins.set(id, {
      ...plugin,
      descriptor: {
        ...plugin.descriptor,
        apiVersion: plugin.descriptor.apiVersion ?? "agent-plugin.v1",
        capabilities: [...(plugin.descriptor.capabilities ?? [])],
        requiredCapabilities: [...(plugin.descriptor.requiredCapabilities ?? [])],
        guardrails: [...(plugin.descriptor.guardrails ?? [])],
        acceptsDelegation: plugin.descriptor.acceptsDelegation ?? true,
        input,
        tools: [...tools],
      },
    });
  }

  get(id: string): AgentPlugin | undefined {
    return this.plugins.get(id);
  }

  list() {
    return [...this.plugins.values()].map(({ descriptor }) => ({
      id: descriptor.id,
      version: descriptor.version,
      name: descriptor.name,
      description: descriptor.description,
      apiVersion: descriptor.apiVersion,
      capabilities: descriptor.capabilities,
      requiredCapabilities: descriptor.requiredCapabilities,
      modelProfile: descriptor.modelProfile,
      acceptsDelegation: descriptor.acceptsDelegation,
      limits: descriptor.limits,
      inputSchema: descriptor.input,
      outputSchema: descriptor.output,
      guardrails: descriptor.guardrails,
      tools: descriptor.tools,
    }));
  }

  findByCapability(capability: string): AgentPlugin[] {
    const normalized = capability.trim().toLowerCase();
    if (!normalized) return [];
    return [...this.plugins.values()].filter((plugin) =>
      plugin.descriptor.capabilities?.some((value) => value.toLowerCase() === normalized),
    );
  }

  delegatable(): AgentPlugin[] {
    return [...this.plugins.values()].filter(
      (plugin) => plugin.descriptor.id !== "orchestrator" && plugin.descriptor.acceptsDelegation,
    );
  }

  plannerCatalog(): PlannerCatalog {
    return {
      findByCapability: (capability): PlannerAgent[] =>
        this.findByCapability(capability).map(({ descriptor }) => ({
          id: descriptor.id,
          version: descriptor.version,
          description: descriptor.description,
          capabilities: descriptor.capabilities ?? [],
        })),
    };
  }
}

export function validateAgentPlugin(plugin: AgentPlugin): void {
  const descriptor = plugin?.descriptor;
  if (!descriptor || typeof descriptor !== "object")
    throw new Error("Agent plugin has no descriptor");
  if (
    descriptor.apiVersion &&
    !["agent-plugin.v1", "agent-plugin.v2"].includes(descriptor.apiVersion)
  ) {
    throw new Error(`Unsupported agent API version '${descriptor.apiVersion}'`);
  }
  if (!descriptor.name.trim() || !descriptor.description.trim()) {
    throw new Error(`Agent '${descriptor.id}' must have a name and description`);
  }
  if (new Set(descriptor.tools).size !== descriptor.tools.length) {
    throw new Error(`Agent '${descriptor.id}' declares duplicate tools`);
  }
  for (const capability of descriptor.capabilities ?? []) {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(capability)) {
      throw new Error(`Invalid capability '${capability}' for agent '${descriptor.id}'`);
    }
  }
  for (const capability of descriptor.requiredCapabilities ?? []) {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(capability)) {
      throw new Error(`Invalid required capability '${capability}' for agent '${descriptor.id}'`);
    }
  }
  const limits = descriptor.limits;
  for (const [name, value] of Object.entries(limits ?? {})) {
    if (value !== undefined && (!Number.isInteger(value) || value < 1)) {
      throw new Error(`Invalid limit '${name}' for agent '${descriptor.id}'`);
    }
  }
}

export async function loadAgentPool(specifiers: readonly string[]): Promise<AgentPool> {
  const registry = new AgentPool();
  for (const specifier of specifiers) {
    const url = specifier.startsWith("file:") ? specifier : pathToFileURL(resolve(specifier)).href;
    const module = await import(url);
    const plugins: unknown[] = Array.isArray(module.plugins)
      ? module.plugins
      : module.agentPlugin
        ? [module.agentPlugin]
        : [];
    if (plugins.length === 0) throw new Error(`Agent module '${specifier}' exports no plugins`);
    for (const plugin of plugins) registry.register(plugin as AgentPlugin);
  }
  return registry;
}

export interface ExternalAgentManifest {
  apiVersion?: "agent-plugin.v2";
  id: string;
  version: string;
  name: string;
  description: string;
  capabilities?: readonly string[];
  requiredCapabilities?: readonly string[];
  modelProfile?: string;
  acceptsDelegation?: boolean;
  limits?: AgentPlugin["descriptor"]["limits"];
  guardrails?: readonly string[];
  tools: readonly string[];
  inputSchema: TSchema;
  outputSchema?: TSchema;
  command: string;
  args?: readonly string[];
  cwd?: string;
}

export async function loadExternalAgentPlugins(
  specifiers: readonly string[],
): Promise<AgentPlugin[]> {
  const plugins: AgentPlugin[] = [];
  for (const specifier of specifiers) {
    const filename = specifier.startsWith("file:")
      ? new URL(specifier)
      : pathToFileURL(resolve(specifier));
    let manifest: unknown;
    try {
      manifest = JSON.parse(await readFile(filename, "utf8"));
    } catch (error) {
      throw new Error(
        `Unable to read external agent manifest '${specifier}': ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    plugins.push(createExternalAgentPlugin(manifest));
  }
  return plugins;
}

export function createExternalAgentPlugin(value: unknown): AgentPlugin {
  if (!isExternalAgentManifest(value)) {
    throw new Error("External agent manifest is invalid");
  }
  const manifest = value;
  const runnerOptions = {
    command: manifest.command,
    args: manifest.args,
    cwd: manifest.cwd,
  };
  return {
    descriptor: {
      apiVersion: "agent-plugin.v2",
      id: manifest.id,
      version: manifest.version,
      name: manifest.name,
      description: manifest.description,
      capabilities: manifest.capabilities,
      requiredCapabilities: manifest.requiredCapabilities,
      modelProfile: manifest.modelProfile,
      acceptsDelegation: manifest.acceptsDelegation,
      limits: manifest.limits,
      guardrails: manifest.guardrails,
      tools: manifest.tools,
      input: manifest.inputSchema,
      output: manifest.outputSchema,
    },
    async run(input, context) {
      const runner = new JsonLineAgentRunner({
        ...runnerOptions,
        onToolCall: (call) =>
          context.pool.call(
            call.name,
            call.input,
            {
              userId: context.userId,
              spaceId: context.spaceId,
              agentId: manifest.id,
              sessionId: context.sessionId,
              runId: context.runId,
              taskId: context.taskId,
              parentRunId: context.parentRunId,
              depth: context.depth,
              toolCallId: call.callId,
              trace: context.trace,
              publish: context.publish,
              signal: context.signal,
            },
            manifest.id,
          ),
      });
      return runner.run(
        {
          requestId: context.runId,
          agentId: manifest.id,
          agentVersion: manifest.version,
          input,
          scope: {
            userId: context.userId,
            spaceId: context.spaceId,
            taskId: context.taskId,
            runId: context.runId,
            parentRunId: context.parentRunId,
            traceId: context.trace?.traceId,
          },
          tools: context.tools.map(({ name }) => name),
          deadlineAt: manifest.limits?.maxDurationMs
            ? new Date(Date.now() + manifest.limits.maxDurationMs).toISOString()
            : undefined,
        },
        context.signal,
      );
    },
  };
}

function isExternalAgentManifest(value: unknown): value is ExternalAgentManifest {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.version === "string" &&
    typeof value.name === "string" &&
    typeof value.description === "string" &&
    typeof value.command === "string" &&
    value.command.trim().length > 0 &&
    Array.isArray(value.tools) &&
    value.tools.every((tool) => typeof tool === "string") &&
    isRecord(value.inputSchema) &&
    (!value.outputSchema || isRecord(value.outputSchema)) &&
    (!value.args ||
      (Array.isArray(value.args) && value.args.every((arg) => typeof arg === "string")))
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
