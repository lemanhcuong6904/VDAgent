/**
 * M6 production CollaborationPort. Discovery reads the registry planner catalog; invocation runs
 * through InMemoryCollaborationPort (per-run request tracking, timeout, status) whose handler is the
 * production `agents.delegate` tool, so authorization, depth and fan-out limits stay host-owned.
 */
import { type AgentContext, DELEGATION_TOOL } from "../agent-contract.js";
import type { AgentManifest, AgentPorts, JsonValue } from "../contracts/index.js";
import { InMemoryCollaborationPort } from "./collaboration-port.js";
import {
  type CallOptions,
  failure,
  granted,
  hostScope,
  ID,
  inactive,
  poolScope,
} from "./host-outcome.js";

const LIMITATION = "Child run tracking is per parent invocation and in process.";

export function createHostCollaborationPort(
  manifest: AgentManifest,
  context: AgentContext,
  correlationId: string,
): AgentPorts["collaboration"] {
  const declared = manifest.requiredPorts.includes("collaboration");
  const scope = hostScope(manifest, context);
  const port = new InMemoryCollaborationPort();
  const pending = new Map<string, Promise<unknown>>();
  const byKey = new Map<string, string>();
  const registered = new Set<string>();
  let invocations = 0;
  const gate = (options: CallOptions, needsGrant: boolean) => {
    if (!declared) return failure("denied", "port_not_declared", correlationId);
    if (needsGrant && !granted(manifest, context, DELEGATION_TOOL))
      return failure("denied", "delegation_not_granted", correlationId);
    if (inactive(options)) return failure("failed", "inactive_call", correlationId);
    return undefined;
  };
  const register = (agentId: string, options: CallOptions) => {
    if (registered.has(agentId)) return;
    registered.add(agentId);
    port.registerAgent(
      { agentId, name: agentId, description: agentId, capabilities: [] },
      {
        async execute(input) {
          const message = typeof input === "string" ? input : JSON.stringify(input);
          const output = await context.pool.call(
            DELEGATION_TOOL,
            { agent: agentId, message },
            poolScope(manifest, context, options.signal),
            manifest.id,
          );
          // The delegation tool reports child failure as text instead of throwing.
          if (typeof output === "string" && output.startsWith("error: ")) {
            throw new Error(output.slice(7));
          }
          return output;
        },
      },
    );
  };

  return {
    async discover(input, options) {
      const denied = gate(options, false);
      if (denied) return denied;
      const agents = (context.catalog?.findByCapability(input.capability) ?? [])
        .filter((agent) => agent.id !== manifest.id)
        .slice(0, input.limit)
        .map((agent) => ({
          agentId: agent.id,
          version: agent.version,
          capabilities: [...agent.capabilities],
        }));
      return { status: "ok", output: agents, evidence: [], limitations: [LIMITATION] };
    },
    async invoke(input, options) {
      const denied = gate(options, true);
      if (denied) return denied;
      if (!ID.test(input.idempotencyKey))
        return failure("denied", "invalid_idempotency_key", correlationId);
      const existing = byKey.get(input.idempotencyKey);
      if (existing)
        return { status: "ok", output: { runId: existing }, evidence: [], limitations: [] };
      if (++invocations > manifest.limits.maxChildRuns)
        return failure("denied", "child_run_limit", correlationId);
      const runId = `${scope.runId}.child.${invocations}`.slice(0, 128);
      byKey.set(input.idempotencyKey, runId);
      register(input.agentId, options);
      pending.set(
        runId,
        port.invoke({
          requestId: runId,
          callerRunId: scope.runId,
          targetAgentId: input.agentId,
          scope,
          input: input.input,
          timeout: Math.max(1, options.deadline - Date.now()),
          traceId: scope.traceId,
        }),
      );
      return { status: "ok", output: { runId }, evidence: [], limitations: [LIMITATION] };
    },
    async wait(input, options) {
      const denied = gate(options, false);
      if (denied) return denied;
      const unknown = input.runIds.find((runId) => !pending.has(runId));
      if (unknown) return failure("failed", "unknown_child_run", correlationId);
      const remaining = Math.max(0, options.deadline - Date.now());
      await Promise.race([
        Promise.allSettled(input.runIds.map((runId) => pending.get(runId))),
        new Promise((resolve) => setTimeout(resolve, remaining).unref()),
      ]);
      const completedRunIds: string[] = [];
      for (const runId of input.runIds) {
        if (await port.getStatus(runId)) completedRunIds.push(runId);
      }
      return { status: "ok", output: { completedRunIds }, evidence: [], limitations: [LIMITATION] };
    },
    async result(input, options) {
      const denied = gate(options, false);
      if (denied) return denied;
      if (!pending.has(input.runId)) return failure("failed", "unknown_child_run", correlationId);
      const result = await port.getStatus(input.runId);
      const status = !result
        ? ("running" as const)
        : result.status === "completed"
          ? ("completed" as const)
          : result.status === "cancelled"
            ? ("cancelled" as const)
            : ("failed" as const);
      return {
        status: "ok",
        output: {
          status,
          ...(status === "completed" && {
            output: JSON.parse(JSON.stringify(result?.output ?? null)) as JsonValue,
          }),
          artifacts: [],
        },
        evidence: [],
        limitations: [LIMITATION],
      };
    },
  };
}
