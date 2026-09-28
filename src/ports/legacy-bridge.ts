import { Ajv2020 } from "ajv/dist/2020.js";
import type { AgentContext, AgentPlugin } from "../agent-contract.js";
import {
  type AgentExecutionContext,
  type AgentManifest,
  AgentManifestSchema,
  type AgentModule,
  type AgentResult,
  AgentScopeSchema,
  type JsonValue,
} from "../contracts/index.js";
import { encodeBoundedJson } from "../testkit/json.js";

const ajv = new Ajv2020({ strict: true });
const validateManifest = ajv.compile(AgentManifestSchema);
const validateScope = ajv.compile(AgentScopeSchema);

/** Private host bindings must be supplied explicitly; never fabricate scope or grants. */
export type LegacyContextFactory = (context: AgentExecutionContext<JsonValue>) => AgentContext;

/** The legacy plugin returns domain output, not a success/wait envelope. */
export class LegacyAgentAdapter implements AgentModule<JsonValue, JsonValue> {
  readonly manifest: AgentManifest;
  private readonly validateInput;
  private readonly validateOutput;

  constructor(
    private readonly plugin: AgentPlugin,
    manifest: AgentManifest,
    private readonly createContext: LegacyContextFactory,
  ) {
    if (!validateManifest(manifest)) throw new Error("Invalid agent manifest");
    if (plugin.descriptor.id !== manifest.id || plugin.descriptor.version !== manifest.version)
      throw new Error("Legacy plugin identity does not match manifest");
    this.manifest = structuredClone(manifest);
    this.validateInput = ajv.compile(manifest.inputSchema);
    this.validateOutput = ajv.compile(manifest.outputSchema);
  }

  async execute(ctx: AgentExecutionContext<JsonValue>): Promise<AgentResult<JsonValue>> {
    ctx.signal.throwIfAborted();
    if (!Number.isFinite(ctx.deadline) || ctx.deadline <= Date.now())
      throw new Error("Agent deadline exceeded");
    if (
      !validateScope(ctx.scope) ||
      ctx.scope.agentId !== this.manifest.id ||
      ctx.scope.agentVersion !== this.manifest.version
    )
      throw new Error("Agent scope does not match manifest");
    encodeBoundedJson(ctx.input, this.manifest.limits.maxInputBytes);
    if (!this.validateInput(ctx.input)) throw new Error("Invalid agent input");
    const legacy = this.createContext(ctx);
    if (
      legacy.userId !== ctx.scope.actorId ||
      legacy.spaceId !== ctx.scope.workspaceId ||
      legacy.runId !== ctx.scope.runId
    )
      throw new Error("Legacy context identity mismatch");
    const controller = new AbortController();
    const signal = AbortSignal.any([ctx.signal, controller.signal]);
    const timeout = setTimeout(
      () => controller.abort(new Error("Agent deadline exceeded")),
      Math.min(ctx.deadline - Date.now(), this.manifest.limits.timeoutMs),
    );
    const started = Date.now();
    let onAbort = () => {};
    try {
      const output = await Promise.race([
        Promise.resolve().then(() => {
          signal.throwIfAborted();
          return this.plugin.run(structuredClone(ctx.input), { ...legacy, signal });
        }),
        new Promise<never>((_, reject) => {
          onAbort = () => reject(signal.reason);
          signal.addEventListener("abort", onAbort, { once: true });
          if (signal.aborted) onAbort();
        }),
      ]);
      signal.throwIfAborted();
      const encoded = encodeBoundedJson(output, this.manifest.limits.maxOutputBytes);
      if (!this.validateOutput(output)) throw new Error("Invalid agent output");
      return {
        status: "completed",
        output: JSON.parse(encoded),
        artifacts: [],
        evidence: [],
        usage: {
          inputTokens: 0,
          outputTokens: 0,
          cacheReadTokens: 0,
          cacheWriteTokens: 0,
          modelCalls: 0,
          toolCalls: 0,
          durationMs: Date.now() - started,
          estimatedCostUsd: 0,
        },
        warnings: ["Legacy output only; usage and evidence are not collected by this adapter."],
      };
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", onAbort);
    }
  }
}

export class LegacyAgentRegistry {
  private readonly adapters = new Map<string, LegacyAgentAdapter>();
  register(
    id: string,
    plugin: AgentPlugin,
    manifest: AgentManifest,
    factory: LegacyContextFactory,
  ) {
    if (id !== manifest.id || this.adapters.has(id))
      throw new Error("Invalid or duplicate agent ID");
    const adapter = new LegacyAgentAdapter(plugin, manifest, factory);
    this.adapters.set(id, adapter);
  }
  get(id: string) {
    return this.adapters.get(id);
  }
  list() {
    return [...this.adapters].map(([id, adapter]) => ({
      id,
      manifest: structuredClone(adapter.manifest),
    }));
  }
}
