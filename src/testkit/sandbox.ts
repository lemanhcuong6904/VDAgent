import { Ajv2020 } from "ajv/dist/2020.js";
import type { AgentScope } from "../contracts/generated/agent-scope.js";
import { AgentScopeSchema } from "../contracts/generated/agent-scope.js";
import type { ArtifactRef } from "../contracts/generated/artifact-ref.js";
import { ArtifactRefSchema } from "../contracts/generated/artifact-ref.js";
import type {
  CallOptions,
  JsonSchema,
  JsonValue,
  PortOutcome,
  SandboxPort,
} from "../contracts/ports.js";
import { type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";
import { createFakeToolPort, type FakeTool } from "./tools.js";

export interface SandboxFixture {
  commandId: string;
  argumentSchema: JsonSchema;
  artifacts: ArtifactRef[];
  /** Synthetic output is byte-checked but never returned as evidence or a terminal receipt. */
  run(
    arguments_: JsonValue,
    signal: AbortSignal,
  ): Promise<{ exitCode: number | null; output: string }>;
}
/** No shell, network, credentials or filesystem access: lifecycle fixtures only. */
export function createFakeSandboxPort(config: {
  scope: AgentScope;
  clock: TestClock;
  commands: SandboxFixture[];
  inputArtifacts: readonly string[];
  credentialRefs: readonly string[];
  maxInstances: number;
  maxMutations: number;
  maxInputBytes: number;
  maxOutputBytes: number;
  before?: (operation: "execute" | "pause" | "resume", signal: AbortSignal) => Promise<void>;
}): SandboxPort {
  const { clock, maxInstances, maxMutations, maxInputBytes, maxOutputBytes, before } = config;
  for (const limit of [maxInstances, maxMutations, maxInputBytes, maxOutputBytes])
    if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("Invalid sandbox limits");
  const ajv = new Ajv2020({ strict: true });
  const scope = JSON.parse(encodeBoundedJson(config.scope, maxInputBytes)) as AgentScope;
  if (!ajv.compile(AgentScopeSchema)(scope)) throw new Error("Invalid sandbox scope");
  const validateArtifact = ajv.compile(ArtifactRefSchema);
  const commands = new Map(
    config.commands.map((command) => {
      if (!validId(command.commandId)) throw new Error("Invalid command identity");
      const argumentSchema = JSON.parse(encodeBoundedJson(command.argumentSchema, maxInputBytes));
      const artifacts = JSON.parse(
        encodeBoundedJson(command.artifacts, maxOutputBytes),
      ) as ArtifactRef[];
      if (
        artifacts.some(
          (artifact) =>
            !validateArtifact(artifact) ||
            artifact.status !== "ready" ||
            artifact.workspaceId !== scope.workspaceId ||
            artifact.ownerRunId !== scope.runId,
        )
      )
        throw new Error("Invalid sandbox artifact fixture");
      return [
        command.commandId,
        { validate: ajv.compile(argumentSchema), artifacts, run: command.run },
      ] as const;
    }),
  );
  if (commands.size !== config.commands.length) throw new Error("Duplicate command fixture");
  const inputArtifacts = new Set(config.inputArtifacts);
  const credentialRefs = new Set(config.credentialRefs);
  if ([...inputArtifacts, ...credentialRefs].some((id) => !validId(id)))
    throw new Error("Invalid sandbox reference grant");
  const instances = new Map<
    string,
    { status: "running" | "paused" | "stopped" | "unknown"; parentCheckpoint: string | null }
  >();
  const checkpoints = new Map<string, { sourceExecution: string }>();
  const denied = (code: string, unknown = false): PortOutcome<JsonValue> => {
    const error = {
      code,
      retryable: false as const,
      safeMessage: code,
      correlationId: scope.traceId,
    };
    return unknown
      ? { status: "unknown", error: { ...error, class: "unknown" }, evidence: [] }
      : { status: "denied", error: { ...error, class: "policy" }, evidence: [] };
  };
  const ok = (output: JsonValue): PortOutcome<JsonValue> => ({
    status: "ok",
    output,
    evidence: [],
    limitations: ["Synthetic sandbox lifecycle; not proof of container isolation"],
  });
  async function gate(operation: "execute" | "pause" | "resume", signal: AbortSignal) {
    if (before) await before(operation, signal);
    if (signal.aborted) throw new Error("inactive_call");
  }
  const tools = new Map<string, FakeTool>([
    [
      "execute",
      {
        effect: "write",
        execute: async (raw, _scope, signal) => {
          const value = raw as Parameters<SandboxPort["execute"]>[0];
          const command = commands.get(value.commandId);
          if (!command) return denied("command_not_granted");
          if (!command.validate(value.arguments)) return denied("invalid_arguments");
          if (
            !Array.isArray(value.inputArtifacts) ||
            value.inputArtifacts.some((id) => !inputArtifacts.has(id)) ||
            !Array.isArray(value.credentialRefs) ||
            value.credentialRefs.some((id) => !credentialRefs.has(id))
          )
            return denied("reference_not_granted");
          if (
            !Number.isSafeInteger(value.maxOutputBytes) ||
            value.maxOutputBytes < 1 ||
            value.maxOutputBytes > maxOutputBytes
          )
            return denied("output_limit");
          await gate("execute", signal);
          if (instances.size >= maxInstances) return denied("instance_limit");
          const executionId = `fake-execution-${instances.size + 1}`;
          // Reserve before awaiting the fixture; unknown effects retain capacity and cannot be paused.
          instances.set(executionId, { status: "unknown", parentCheckpoint: null });
          const result = await command.run(value.arguments, signal);
          if (signal.aborted) throw new Error("inactive_call");
          if (
            !result ||
            typeof result.output !== "string" ||
            !(
              result.exitCode === null ||
              (Number.isSafeInteger(result.exitCode) &&
                result.exitCode >= 0 &&
                result.exitCode <= 255)
            )
          )
            throw new Error("invalid_fixture_output");
          if (new TextEncoder().encode(result.output).byteLength > value.maxOutputBytes)
            return denied("output_limit", true);
          const outcome = ok({
            executionId,
            exitCode: result.exitCode,
            artifacts: command.artifacts,
          });
          encodeBoundedJson(outcome, maxOutputBytes);
          instances.set(executionId, {
            status: result.exitCode === null ? "running" : "stopped",
            parentCheckpoint: null,
          });
          return outcome;
        },
      },
    ],
    [
      "pause",
      {
        effect: "write",
        execute: async (raw, _scope, signal) => {
          const value = raw as Parameters<SandboxPort["pause"]>[0];
          await gate("pause", signal);
          const instance = instances.get(value.executionId);
          if (instance?.status !== "running") return denied("execution_not_running");
          const checkpointId = `fake-checkpoint-${checkpoints.size + 1}`;
          const outcome = ok({ checkpointId });
          encodeBoundedJson(outcome, maxOutputBytes);
          checkpoints.set(checkpointId, { sourceExecution: value.executionId });
          instance.status = "paused";
          return outcome;
        },
      },
    ],
    [
      "resume",
      {
        effect: "write",
        execute: async (raw, _scope, signal) => {
          const value = raw as Parameters<SandboxPort["resume"]>[0];
          await gate("resume", signal);
          if (!checkpoints.has(value.checkpointId)) return denied("checkpoint_unavailable");
          if (instances.size >= maxInstances) return denied("instance_limit");
          const executionId = `fake-execution-${instances.size + 1}`;
          const outcome = ok({ executionId });
          encodeBoundedJson(outcome, maxOutputBytes);
          instances.set(executionId, { status: "running", parentCheckpoint: value.checkpointId });
          return outcome;
        },
      },
    ],
  ]);
  const port = createFakeToolPort({
    scope,
    grants: ["execute", "pause", "resume"],
    tools,
    clock,
    maxInputBytes,
    maxOutputBytes,
    maxExecutions: maxMutations,
  });
  async function invoke<T>(
    operation: string,
    input: { idempotencyKey: string },
    fields: string[],
    options: CallOptions,
  ): Promise<PortOutcome<T>> {
    let value: { idempotencyKey: string };
    try {
      value = JSON.parse(encodeBoundedJson(input, maxInputBytes));
      if (
        !value ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== fields.length ||
        fields.some((field) => !Object.hasOwn(value, field)) ||
        !validId(value.idempotencyKey)
      )
        return denied("invalid_sandbox_request") as PortOutcome<T>;
    } catch {
      return denied("invalid_sandbox_request") as PortOutcome<T>;
    }
    const result = await port.invoke(
      { toolId: operation, input: canonicalValue(value), idempotencyKey: value.idempotencyKey },
      options,
    );
    // These tools are private fixtures above; external output never selects an outcome shape.
    return (result.status === "ok" ? result.output : result) as PortOutcome<T>;
  }
  return {
    execute: (input, options) =>
      invoke(
        "execute",
        input,
        [
          "commandId",
          "arguments",
          "inputArtifacts",
          "credentialRefs",
          "maxOutputBytes",
          "idempotencyKey",
        ],
        options,
      ),
    pause: (input, options) => invoke("pause", input, ["executionId", "idempotencyKey"], options),
    resume: (input, options) =>
      invoke("resume", input, ["checkpointId", "idempotencyKey"], options),
  };
}
const validId = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
function canonicalValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalValue(value[key])]),
    );
  return value;
}
