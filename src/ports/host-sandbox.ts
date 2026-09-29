/**
 * Production SandboxPort. Agents never send argv: they name a host-owned `commandId`, the host
 * validates its arguments and builds argv, then runs it through the `sandbox.execute` pool tool
 * (SandboxSupervisor + Docker: no network, read-only rootfs, capped memory/CPU/pids).
 * Every call is checked by `evaluateSandboxPolicy`; the default policy allows no egress and no
 * credentials, so any credential or input-artifact reference is denied until a broker exists.
 * Execution is synchronous, so pause/resume are honestly unsupported.
 */
import { createHash } from "node:crypto";
import type { AgentContext } from "../agent-contract.js";
import type { AgentManifest, AgentPorts, JsonValue } from "../contracts/index.js";
import {
  DEFAULT_SANDBOX_POLICY,
  evaluateSandboxPolicy,
  type SandboxPolicy,
} from "../sandbox-policy.js";
import {
  type CallOptions,
  failure,
  granted,
  hostScope,
  ID,
  inactive,
  poolScope,
} from "./host-outcome.js";

/** A host-registered command: validates agent arguments and returns argv, or undefined if invalid. */
export type SandboxCommandSpec = { build(args: JsonValue): string[] | undefined };

const MAX_SOURCE = 16_000;
export const SANDBOX_COMMANDS: Readonly<Record<string, SandboxCommandSpec>> = {
  // Runs a JavaScript snippet with Node inside the container. Output is whatever it prints.
  "node.eval": {
    build(args) {
      if (typeof args !== "object" || args === null || Array.isArray(args)) return undefined;
      const { source, ...rest } = args as Record<string, JsonValue>;
      if (Object.keys(rest).length || typeof source !== "string") return undefined;
      if (!source.length || source.length > MAX_SOURCE) return undefined;
      return ["node", "-e", source];
    },
  },
};

type RawResult = { exitCode: number | null; output: { stdout: string; stderr: string } };
type ExecuteResult = Awaited<ReturnType<NonNullable<AgentPorts["sandbox"]>["execute"]>>;

export function createHostSandboxPort(
  manifest: AgentManifest,
  context: AgentContext,
  correlationId: string,
  options: { commands?: Readonly<Record<string, SandboxCommandSpec>>; policy?: SandboxPolicy } = {},
): NonNullable<AgentPorts["sandbox"]> {
  const commands = options.commands ?? SANDBOX_COMMANDS;
  const policy = options.policy ?? DEFAULT_SANDBOX_POLICY;
  const declared = manifest.requiredPorts.includes("sandbox");
  const scope = hostScope(manifest, context);
  const replay = new Map<string, ExecuteResult>();
  let executions = 0;
  const gate = (call: CallOptions) => {
    if (!declared) return failure("denied", "port_not_declared", correlationId);
    if (!granted(manifest, context, "sandbox.execute"))
      return failure("denied", "sandbox_not_granted", correlationId);
    if (inactive(call)) return failure("failed", "inactive_call", correlationId);
    return undefined;
  };
  const unsupported = async (call: CallOptions) =>
    gate(call) ?? failure("denied", "sandbox_pause_unsupported", correlationId);

  return {
    async execute(input, call) {
      const denied = gate(call);
      if (denied) return denied;
      if (!ID.test(input.idempotencyKey))
        return failure("denied", "invalid_idempotency_key", correlationId);
      const cached = replay.get(input.idempotencyKey);
      if (cached) return cached;
      const spec = Object.hasOwn(commands, input.commandId) ? commands[input.commandId] : undefined;
      if (!spec) return failure("denied", "unknown_command", correlationId);
      const argv = spec.build(input.arguments);
      if (!argv) return failure("denied", "invalid_command_arguments", correlationId);
      if (input.inputArtifacts.length)
        return failure("denied", "sandbox_input_artifacts_unsupported", correlationId);
      const violations = evaluateSandboxPolicy(policy, {
        command: argv[0] ?? "",
        args: argv.slice(1),
        credentials: input.credentialRefs,
      });
      if (violations.length)
        return failure("denied", `sandbox_policy_${violations[0]?.rule}`, correlationId);

      const timeoutMs = Math.max(
        1,
        Math.min(policy.resources.timeoutMs, call.deadline - Date.now()),
      );
      let raw: RawResult;
      try {
        raw = (await context.pool.call(
          "sandbox.execute",
          { argv, timeoutMs },
          poolScope(manifest, context, call.signal, input.idempotencyKey),
          manifest.id,
        )) as RawResult;
      } catch {
        // The command may have changed the workspace before failing: never report a clean failure.
        return failure("unknown", "sandbox_outcome_unknown", correlationId);
      }
      const content = Buffer.from(JSON.stringify(raw.output));
      if (content.byteLength > input.maxOutputBytes)
        return failure("unknown", "output_limit", correlationId);

      const executionId = `${scope.runId}.exec.${++executions}`;
      const limitations = [
        "Runs synchronously in a network-isolated Docker container; pause/resume are not supported.",
      ];
      let artifacts: Extract<ExecuteResult, { status: "ok" }>["output"]["artifacts"] = [];
      if (granted(manifest, context, "artifacts.store")) {
        try {
          const stored = (await context.pool.call(
            "artifacts.store",
            {
              kind: "sandbox.output",
              version: "1",
              mediaType: "application/json",
              bytesBase64: content.toString("base64"),
            },
            poolScope(manifest, context, call.signal, `${input.idempotencyKey}.output`),
            manifest.id,
          )) as { id: string; sha256: string; bytes: number };
          artifacts = [
            {
              id: stored.id,
              workspaceId: scope.workspaceId,
              ownerRunId: scope.runId,
              kind: "sandbox.output",
              version: "1",
              status: "ready",
              sha256: createHash("sha256").update(content).digest("hex"),
              bytes: content.byteLength,
            },
          ];
        } catch {
          limitations.push("Output could not be stored as an artifact.");
        }
      } else limitations.push("Output is not persisted: artifacts.store is not granted.");

      const result: ExecuteResult = {
        status: "ok",
        output: { executionId, exitCode: raw.exitCode, artifacts },
        evidence: [],
        limitations,
      };
      replay.set(input.idempotencyKey, result);
      return result;
    },
    pause: (_input, call) => unsupported(call),
    resume: (_input, call) => unsupported(call),
  };
}
