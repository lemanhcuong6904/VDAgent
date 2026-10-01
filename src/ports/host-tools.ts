/**
 * M4 production ToolPort. Each invocation gets a ToolPool whose registry holds only the grant
 * intersection (manifest.toolGrants ∩ pool allowlist), converted through the default-deny
 * McpToolAdapter. ToolPool enforces byte limits, deadline and timeout and records executions;
 * McpToolPool.call performs the effect under host-bound identity.
 */
import type { AgentContext } from "../agent-contract.js";
import type { AgentManifest, AgentPorts, EvidenceRef, JsonValue } from "../contracts/index.js";
import {
  type CallOptions,
  failure,
  granted,
  hostScope,
  ID,
  inactive,
  type Outcome,
  poolScope,
} from "./host-outcome.js";
import { McpToolAdapter } from "./mcp-adapter.js";
import { ToolPool } from "./tool-pool.js";
import type { EffectClass, ToolResult } from "./tool-port.js";

const SERVER = "host";
/** Learned from pi-mcp-adapter: a failing tool is blocked briefly instead of being hammered. */
export const TOOL_FAILURE_BACKOFF_MS = 60_000;
const EFFECT: Record<AgentManifest["toolGrants"][number]["effect"], EffectClass> = {
  read: "read",
  write: "write",
  external: "network",
};

export function createHostToolPort(
  manifest: AgentManifest,
  context: AgentContext,
  correlationId: string,
): AgentPorts["tools"] {
  const declared = manifest.requiredPorts.includes("tools");
  const grants = manifest.toolGrants.filter((grant) => granted(manifest, context, grant.toolId));
  const adapter = new McpToolAdapter();
  const registry = new ToolPool();
  const scope = hostScope(manifest, context);
  adapter.registerServer({ id: SERVER, capabilities: [], tools: [] });
  adapter.setAllowlist(
    SERVER,
    grants.map((grant) => grant.toolId),
  );
  // The handler receives only ToolContext, so the per-call signal travels by idempotency key.
  const signals = new Map<string, AbortSignal>();
  for (const grant of grants) {
    const tool = context.tools.find(({ name }) => name === grant.toolId);
    if (!tool) continue;
    const converted = adapter.convertToManifest({
      mcpTool: {
        name: tool.name,
        description: tool.description,
        inputSchema: { type: "object", properties: {} },
      },
      serverId: SERVER,
      version: grant.version,
      effectClass: EFFECT[grant.effect],
      // Replays are deduplicated by the host outcome cache below, not by the registry.
      idempotent: false,
      sensitivity: "internal",
      limits: {
        maxInputBytes: manifest.limits.maxInputBytes,
        maxOutputBytes: manifest.limits.maxOutputBytes,
        timeoutMs: (tool.timeoutMs ?? 30_000) + 1_000,
      },
    });
    registry.register({
      manifest: { ...converted, id: grant.toolId },
      registeredBy: "host-factory",
      handler: (input, toolContext) =>
        context.pool.call(
          grant.toolId,
          input,
          poolScope(
            manifest,
            context,
            signals.get(toolContext.idempotencyKey ?? "") ?? context.signal,
            toolContext.idempotencyKey,
          ),
          manifest.id,
        ),
    });
  }

  // Per-run replay cache: an ok or unknown outcome is returned again, never re-executed.
  const outcomes = new Map<string, Awaited<ReturnType<AgentPorts["tools"]["invoke"]>>>();
  const inputHashes = new Map<string, string>();
  const inFlight = new Map<string, Promise<Awaited<ReturnType<AgentPorts["tools"]["invoke"]>>>>();
  const failedAt = new Map<string, number>();
  let calls = 0;
  return {
    async invoke(input, options: CallOptions) {
      const replayKey = `${input.toolId}:${input.idempotencyKey}`;
      const inputHash = stableJson(input.input);
      const previousHash = inputHashes.get(replayKey);
      if (previousHash !== undefined && previousHash !== inputHash)
        return failure("denied", "idempotency_conflict", correlationId);
      inputHashes.set(replayKey, inputHash);
      const replay = outcomes.get(replayKey);
      if (replay) return replay;
      const pending = inFlight.get(replayKey);
      if (pending) return pending;
      const execution = thisInvoke(input, options);
      inFlight.set(replayKey, execution);
      try {
        return await execution;
      } finally {
        if (inFlight.get(replayKey) === execution) inFlight.delete(replayKey);
      }
    },
  };

  async function thisInvoke(
    input: Parameters<AgentPorts["tools"]["invoke"]>[0],
    options: CallOptions,
  ) {
    if (!declared) return failure("denied", "port_not_declared", correlationId);
    const grant = grants.find((entry) => entry.toolId === input.toolId);
    if (!grant) return failure("denied", "tool_not_granted", correlationId);
    if (!ID.test(input.idempotencyKey))
      return failure("denied", "invalid_idempotency_key", correlationId);
    const replay = outcomes.get(`${input.toolId}:${input.idempotencyKey}`);
    if (replay) return replay;
    if (inactive(options)) return failure("failed", "inactive_call", correlationId);
    const lastFailure = failedAt.get(input.toolId);
    if (lastFailure !== undefined && Date.now() - lastFailure < TOOL_FAILURE_BACKOFF_MS)
      return failure("failed", "tool_backoff", correlationId);
    if (++calls > manifest.limits.maxToolCalls)
      return failure("denied", "tool_call_limit", correlationId);
    signals.set(input.idempotencyKey, options.signal);
    let result: ToolResult<unknown>;
    try {
      result = await registry.invoke({
        toolId: input.toolId,
        input: input.input,
        context: {
          runId: scope.runId,
          attemptId: scope.attemptId,
          scope,
          idempotencyKey: input.idempotencyKey,
          deadline: options.deadline,
          fence: scope.fence,
        },
      });
    } finally {
      signals.delete(input.idempotencyKey);
    }
    const outcome = mapResult(result, grant.effect, scope, correlationId);
    if (outcome.status === "failed" || outcome.status === "unknown")
      failedAt.set(input.toolId, Date.now());
    if (outcome.status === "ok" || outcome.status === "unknown") {
      outcomes.set(`${input.toolId}:${input.idempotencyKey}`, outcome);
    }
    return outcome;
  }
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
    .join(",")}}`;
}

function mapResult(
  result: ToolResult<unknown>,
  effect: AgentManifest["toolGrants"][number]["effect"],
  scope: ReturnType<typeof hostScope>,
  correlationId: string,
): Awaited<ReturnType<AgentPorts["tools"]["invoke"]>> {
  if (result.status === "success") {
    const evidence: EvidenceRef[] = (result.evidence ?? []).map((entry) => ({
      id: entry.id.replace(/[^A-Za-z0-9._:-]/g, "_").slice(0, 128),
      workspaceId: scope.workspaceId,
      runId: scope.runId,
      attemptId: scope.attemptId,
      fence: scope.fence,
      policyRevision: scope.policyRevision,
      // The execution record proves the handler returned, not what the effect did.
      kind: "claim",
      verification: "unverified",
    }));
    return {
      status: "ok",
      output: JSON.parse(JSON.stringify(result.output ?? null)) as JsonValue,
      evidence,
      limitations: ["Replay cache is per run and in process; it does not survive a worker crash."],
    };
  }
  const code = result.error?.code;
  // Rejected before the handler ran: no side effect is possible.
  if (code === "input_too_large") return failure("failed", "tool_input_limit", correlationId);
  if (code === "deadline_exceeded") return failure("failed", "inactive_call", correlationId);
  const mapped = code === "output_too_large" ? "tool_output_limit" : "tool_failed";
  // A write may have happened before the failure surfaced: never report it as clean.
  if (effect === "read") return failure("failed", mapped, correlationId);
  return failure(
    "unknown",
    mapped === "tool_failed" ? "tool_outcome_unknown" : mapped,
    correlationId,
  ) as Outcome;
}
