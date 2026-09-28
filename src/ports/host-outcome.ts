/** Shared helpers for host port providers: canonical ids, fail-closed outcomes, pool scope. */
import type { AgentContext } from "../agent-contract.js";
import type { AgentManifest, AgentScope, PortOutcome } from "../contracts/index.js";
import type { ToolScope } from "../tool-pool.js";

export const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
export type Outcome = PortOutcome<never>;
export type CallOptions = { signal: AbortSignal; deadline: number };

/** Canonical ids are bounded; legacy values that do not fit are hashed into a stable safe form. */
export function safeId(value: string | undefined, fallback: string): string {
  if (value && ID.test(value)) return value;
  if (!value) return fallback;
  let hash = 0;
  for (const char of value) hash = (Math.imul(hash, 31) + char.charCodeAt(0)) >>> 0;
  return `h${hash.toString(16)}`;
}

/** Host-owned canonical scope. tenantId = spaceId: the legacy runtime has no separate tenant. */
export function hostScope(manifest: AgentManifest, context: AgentContext): AgentScope {
  const runId = safeId(context.runId, "run");
  return {
    tenantId: safeId(context.spaceId, "space"),
    workspaceId: safeId(context.spaceId, "space"),
    actorId: safeId(context.userId, "user"),
    audience: "internal",
    taskId: safeId(context.taskId, runId),
    runId,
    attemptId: `${runId}.1`,
    agentId: manifest.id,
    agentVersion: manifest.version,
    policyRevision: `manifest:${manifest.id}@${manifest.version}`.slice(0, 128),
    fence: "1",
    traceId: safeId(context.trace?.traceId, runId),
  };
}

export function failure(
  status: "denied" | "failed" | "unknown",
  code: string,
  correlationId: string,
): Outcome {
  const error = { code, retryable: false as const, safeMessage: code, correlationId };
  if (status === "unknown") return { status, error: { ...error, class: "unknown" }, evidence: [] };
  return {
    status,
    error: { ...error, class: status === "denied" ? "policy" : "validation" },
    evidence: [],
  } as Outcome;
}

export function jsonBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value) ?? "").byteLength;
}

export function inactive(options: CallOptions): boolean {
  return (
    options.signal.aborted || !Number.isFinite(options.deadline) || Date.now() >= options.deadline
  );
}

/** Identity for McpToolPool calls is always host-bound from the invocation context. */
export function poolScope(
  manifest: AgentManifest,
  context: AgentContext,
  signal: AbortSignal,
  toolCallId?: string,
): ToolScope {
  return {
    userId: context.userId,
    spaceId: context.spaceId,
    agentId: manifest.id,
    sessionId: context.sessionId,
    runId: context.runId,
    taskId: context.taskId,
    parentRunId: context.parentRunId,
    depth: context.depth,
    toolCallId,
    trace: context.trace,
    publish: context.publish,
    signal,
  };
}

/** A port is usable only when declared AND its backing pool tools are granted to this agent. */
export function granted(manifest: AgentManifest, context: AgentContext, toolId: string): boolean {
  return (
    manifest.toolGrants.some((grant) => grant.toolId === toolId) &&
    context.tools.some((tool) => tool.name === toolId)
  );
}
