import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { TSchema } from "typebox";
import { type AgentPlugin, canDelegate, DELEGATION_TOOL } from "./agent-contract.js";
import { type PortCall, ProcessAgentRunner } from "./agent-runner.js";
import type { AgentManifest, AgentModule, JsonValue } from "./contracts/index.js";
import type { EvidenceStorage } from "./evidence-storage.js";
import type { PlannerAgent, PlannerCatalog } from "./planner.js";
import { createHostPorts, type HostPortDependencies } from "./ports/host-factory.js";
import { hostScope } from "./ports/host-outcome.js";
import { moduleAsPlugin } from "./ports/module-plugin.js";
import { type ActivationState, AgentRegistry } from "./registry/agent-registry.js";
import { PolicyEngine } from "./registry/policy-engine.js";
import type { MemoryAuditWriter } from "./session/memory-provider.js";
import { WorkflowRegistry } from "./workflow.js";

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
      (plugin) => !canDelegate(plugin.descriptor) && plugin.descriptor.acceptsDelegation,
    );
  }

  plannerCatalog(): PlannerCatalog {
    return {
      findByCapability: (capability): PlannerAgent[] => {
        // Plans only execute delegatable agents; typed modules must not be proposed as steps.
        const agents = (
          capability === "*" ? [...this.plugins.values()] : this.findByCapability(capability)
        ).filter((plugin) => plugin.descriptor.acceptsDelegation !== false);
        return agents.map(({ descriptor }) => ({
          id: descriptor.id,
          version: descriptor.version,
          description: descriptor.description,
          capabilities: descriptor.capabilities ?? [],
        }));
      },
    };
  }
}

export { WorkflowRegistry };

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
  // A delegator that is itself delegatable would allow unbounded delegation chains.
  if (descriptor.tools.includes(DELEGATION_TOOL) && descriptor.acceptsDelegation !== false) {
    throw new Error(`Agent '${descriptor.id}' may delegate only if it does not accept delegation`);
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

export async function loadAgentPool(
  specifiers: readonly string[],
  dependencies: HostPortDependencies = {},
): Promise<AgentPool> {
  const registry = new AgentPool();
  for (const specifier of specifiers) {
    const url = specifier.startsWith("file:") ? specifier : pathToFileURL(resolve(specifier)).href;
    const module = await import(url);
    const plugins: unknown[] = Array.isArray(module.plugins)
      ? module.plugins
      : module.agentPlugin
        ? [module.agentPlugin]
        : [];
    // Canonical agent.v1 modules: activation state decides what serves traffic (M3.1).
    if (Array.isArray(module.agentModules))
      plugins.push(
        ...(await activeModulePlugins(module.agentModules, module.activation ?? {}, dependencies)),
      );
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
  /** Only agent-runner.v2 is supported; omitted means v2. */
  protocol?: "agent-runner.v2";
}

export interface ExternalAgentPluginDeps {
  /** When provided, checkpoint protocol messages are persisted as evidence (M9). */
  evidence?: EvidenceStorage;
  /**
   * When provided, every port call is authorized against real capability/tool
   * grants (M3) instead of the manifest's own declared tool list. Grants are
   * self-seeded per tenant from the manifest on first use, so an agent's
   * existing access is preserved; the engine becomes load-bearing once a
   * caller starts revoking or further restricting grants for a tenant.
   */
  policy?: PolicyEngine;
  /** Durable audit writer for MemoryPort mutations. */
  memoryAudit?: MemoryAuditWriter;
}

/** Tenants that already received self-seeded grants for a given agent, so re-runs don't duplicate them. */
const seededPolicyGrants = new WeakMap<PolicyEngine, Set<string>>();

function ensureSelfGrants(policy: PolicyEngine, manifest: AgentManifest, tenantId: string): void {
  const seeded = seededPolicyGrants.get(policy) ?? new Set<string>();
  seededPolicyGrants.set(policy, seeded);
  const key = `${manifest.id}@${manifest.version}::${tenantId}`;
  if (seeded.has(key)) return;
  seeded.add(key);
  const scope = { tenantId, audience: ["internal"] };
  for (const capability of manifest.capabilities) {
    policy.grant(tenantId, { capability, scope });
  }
  for (const toolGrant of manifest.toolGrants) {
    policy.grant(tenantId, { toolId: toolGrant.toolId, scope });
  }
}

export async function loadExternalAgentPlugins(
  specifiers: readonly string[],
  deps: ExternalAgentPluginDeps = {},
): Promise<AgentPlugin[]> {
  if (specifiers.length > 0) assertExternalAgentIsolationAvailable();
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
    plugins.push(createExternalAgentPlugin(manifest, deps));
  }
  return plugins;
}

/** Only `enabled` versions serve; the shared pool has no per-user canary routing yet. */
export async function activeModulePlugins(
  modules: readonly AgentModule<JsonValue, JsonValue>[],
  activation: Readonly<Record<string, ActivationState>>,
  dependencies: HostPortDependencies = {},
): Promise<AgentPlugin[]> {
  const registry = new AgentRegistry();
  const served: AgentPlugin[] = [];
  for (const agent of modules) {
    const { id, version } = agent.manifest;
    const state = activation[id] ?? "enabled";
    if (state === "canary")
      throw new Error(`Agent '${id}' canary needs per-request routing; not supported by AgentPool`);
    await registry.register({
      id,
      version,
      manifest: agent.manifest,
      activationState: state,
      registeredBy: "deployment",
    });
    if (registry.getActiveVersion(id) === version) served.push(moduleAsPlugin(agent, dependencies));
  }
  return served;
}

/** Process agents on protocol v2 get the same host port factory as in-process modules. */
function externalManifestAsCanonical(manifest: ExternalAgentManifest): AgentManifest {
  return {
    apiVersion: "agent.v1",
    id: manifest.id,
    version: manifest.version,
    displayName: manifest.name,
    inputSchema: manifest.inputSchema as never,
    outputSchema: (manifest.outputSchema ?? true) as never,
    capabilities: [...(manifest.capabilities ?? [])],
    requiredPorts: ["tools", ...(manifest.modelProfile ? ["model" as const] : [])],
    // Effect is not declared by v2 process manifests; "write" keeps failures `unknown`.
    toolGrants: manifest.tools.map((toolId) => ({
      toolId,
      version: "1",
      effect: "write" as const,
    })),
    modelProfile: manifest.modelProfile,
    limits: {
      timeoutMs: manifest.limits?.maxDurationMs ?? 300_000,
      maxInputBytes: 1_048_576,
      maxOutputBytes: 1_048_576,
      maxEventBytes: 65_536,
      maxCheckpointBytes: 1_048_576,
      maxModelCalls: 32,
      maxToolCalls: manifest.limits?.maxToolCalls ?? 32,
      maxChildRuns: manifest.limits?.maxParallelChildren ?? 0,
      maxDepth: manifest.limits?.maxDepth ?? 1,
      maxCostUsd: 1,
    },
    compatibility: { minHostVersion: "1.0.0" },
  };
}

export function createExternalAgentPlugin(
  value: unknown,
  deps: ExternalAgentPluginDeps = {},
): AgentPlugin {
  if (!isExternalAgentManifest(value)) {
    throw new Error("External agent manifest is invalid");
  }
  const manifest = value;
  const runnerOptions = externalRunnerOptions(manifest);
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
      assertExternalAgentIsolationAvailable();
      {
        const canonical = externalManifestAsCanonical(manifest);
        const ports = createHostPorts(canonical, context, {
          memoryAudit: deps.memoryAudit,
        });
        const deadline = Date.now() + canonical.limits.timeoutMs;
        const bridge = async (call: PortCall) => {
          const options = { signal: context.signal, deadline };
          const outcome =
            call.port === "tools"
              ? await ports.tools.invoke(
                  {
                    toolId: call.operation,
                    input: (call.input ?? {}) as JsonValue,
                    idempotencyKey: call.idempotencyKey ?? call.callId,
                  },
                  options,
                )
              : call.port === "model" && call.operation === "complete"
                ? await ports.model.complete(call.input as never, options)
                : null;
          if (!outcome) throw new Error(`Port ${call.port}.${call.operation} is not available`);
          if (outcome.status !== "ok")
            throw new Error("error" in outcome ? outcome.error.safeMessage : outcome.status);
          return outcome.output;
        };
        let checkpointSequence = 0;
        const onCheckpoint = deps.evidence
          ? (checkpointId: string, manifestValue?: unknown) => {
              const sequence = checkpointSequence++;
              deps.evidence
                ?.recordCheckpoint({
                  workspaceId: context.spaceId,
                  runId: context.runId,
                  attemptId: context.runId,
                  checkpointId,
                  checkpointRevision: sequence,
                  metadata: isRecord(manifestValue) ? manifestValue : { checkpointId, sequence },
                })
                .catch(() => {
                  // Evidence recording is best-effort: a storage failure must not fail the run.
                });
            }
          : undefined;
        const policy = deps.policy;
        const scope = policy ? hostScope(canonical, context) : undefined;
        if (policy && scope) ensureSelfGrants(policy, canonical, scope.tenantId);
        return new ProcessAgentRunner({
          ...runnerOptions,
          onPortCall: bridge,
          onCheckpoint,
          authorizationCheck: async (port, operation) => {
            const declared =
              port === "tools"
                ? context.tools.some((tool) => tool.name === operation)
                : port === "model" && canonical.requiredPorts.includes("model");
            if (!declared || !policy || !scope) return declared;
            const toolGrant = canonical.toolGrants.find((grant) => grant.toolId === operation);
            const check =
              port === "tools" && toolGrant
                ? policy.authorize(
                    { ...canonical, capabilities: [], toolGrants: [toolGrant] },
                    scope,
                  )
                : policy.authorize({ ...canonical, capabilities: [], toolGrants: [] }, scope);
            return check.authorized;
          },
        }).run(
          {
            requestId: context.runId,
            agentId: manifest.id,
            agentVersion: manifest.version,
            input,
            scope: {
              user_id: context.userId,
              space_id: context.spaceId,
              task_id: context.taskId,
              run_id: context.runId,
              parent_run_id: context.parentRunId,
              trace_id: context.trace?.traceId,
            },
            tools: context.tools.map(({ name }) => name),
            deadlineAt: new Date(deadline).toISOString(),
          },
          context.signal,
        );
      }
    },
  };
}

/**
 * External plugins run as OS processes under the host account. Filtering the
 * child environment and killing its process group do not isolate its
 * filesystem, credentials in parent-process memory, or kernel access. Until
 * the host launches these plugins in a separate container, production service
 * modes must fail closed instead of treating process separation as a sandbox.
 */
function assertExternalAgentIsolationAvailable(): void {
  if (process.env.NODE_ENV === "production" && process.env.AGENT_ISOLATION_MODE !== "bwrap") {
    throw new Error(
      "External agents require AGENT_ISOLATION_MODE=bwrap in production service mode",
    );
  }
}

/**
 * Run reference agents in a separate user/pid/network namespace. Bubblewrap is
 * deliberately the only production launcher accepted here: it provides a
 * read-only view of the image, a private /tmp and no network while retaining
 * the JSON-lines protocol over the child's stdio.
 */
function externalRunnerOptions(manifest: ExternalAgentManifest): {
  command: string;
  args: readonly string[];
  cwd?: string;
} {
  if (process.env.NODE_ENV !== "production") {
    return { command: manifest.command, args: manifest.args ?? [], cwd: manifest.cwd };
  }
  if (process.env.AGENT_ISOLATION_MODE !== "bwrap") {
    return { command: manifest.command, args: manifest.args ?? [], cwd: manifest.cwd };
  }
  const invocation = productionAgentInvocation(manifest);
  // Bind only the image paths needed by the reference runner. Binding `/` would
  // expose deployment mounts (in particular the worker's Docker socket) to the
  // child even though the socket is mounted read-only in Compose.
  const args = [
    "--seccomp",
    "3",
    ...["/app", "/usr", "/bin", "/lib", "/lib64", "/etc"].flatMap((path) => [
      "--ro-bind",
      path,
      path,
    ]),
    "--proc",
    "/proc",
    "--tmpfs",
    "/dev",
    ...["null", "zero", "full", "random", "urandom"].flatMap((device) => [
      "--ro-bind",
      `/dev/${device}`,
      `/dev/${device}`,
    ]),
    "--symlink",
    "/proc/self/fd",
    "/dev/fd",
    "--symlink",
    "/proc/self/fd/0",
    "/dev/stdin",
    "--symlink",
    "/proc/self/fd/1",
    "/dev/stdout",
    "--symlink",
    "/proc/self/fd/2",
    "/dev/stderr",
    "--tmpfs",
    "/tmp",
    "--tmpfs",
    "/run",
    "--dir",
    "/var",
    "--unshare-user",
    "--unshare-ipc",
    "--unshare-pid",
    "--unshare-uts",
    "--unshare-net",
    "--unshare-cgroup-try",
    "--die-with-parent",
    "--new-session",
    "--chdir",
    manifest.cwd ?? "/app",
    "--",
    invocation.command,
    ...invocation.args,
  ];
  // Bubblewrap reads its child-only BPF filter from fd 3 after namespace setup.
  // The launcher opens the packaged filter, then execs bwrap without retaining a
  // shell process between the host and the agent.
  return {
    command: "/bin/sh",
    args: ["-c", 'exec bwrap "$@" 3</app/agent-seccomp.bpf', "bwrap", ...args],
    cwd: undefined,
  };
}

/**
 * `uv run` cannot probe the interpreter after bwrap creates its user namespace
 * (uv receives EACCES even though Python itself is executable there). Resolve
 * the image's frozen project invocation to its already materialized venv Python
 * before entering bwrap. Keep arbitrary external commands unchanged.
 */
function productionAgentInvocation(manifest: ExternalAgentManifest): {
  command: string;
  args: readonly string[];
} {
  const args = manifest.args ?? [];
  if (
    manifest.command === "uv" &&
    args[0] === "run" &&
    args[1] === "--no-sync" &&
    args[2] === "--project" &&
    args[3] === "agents" &&
    args[4] === "python" &&
    typeof args[5] === "string" &&
    args[5].startsWith("agents/")
  ) {
    return { command: "/app/agents/.venv/bin/python", args: args.slice(5) };
  }
  return { command: manifest.command, args };
}

function isExternalAgentManifest(value: unknown): value is ExternalAgentManifest {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.version === "string" &&
    typeof value.name === "string" &&
    typeof value.description === "string" &&
    typeof value.command === "string" &&
    (value.protocol === undefined || value.protocol === "agent-runner.v2") &&
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
