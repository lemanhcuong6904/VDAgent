import type { AgentScope, JsonValue, PortOutcome, ToolPort } from "../contracts/index.js";
import { awaitFakeReplay, runFakeCall, type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";

export interface FakeTool {
  effect: "read" | "write";
  execute(input: JsonValue, scope: Readonly<AgentScope>, signal: AbortSignal): Promise<JsonValue>;
}
/** A scoped in-memory test double; never substitute this for the durable host effect ledger. */
export function createFakeToolPort(config: {
  scope: AgentScope;
  grants: readonly string[];
  tools: ReadonlyMap<string, FakeTool>;
  clock: TestClock;
  maxInputBytes: number;
  maxOutputBytes: number;
  maxExecutions: number;
}): ToolPort {
  for (const limit of [config.maxInputBytes, config.maxOutputBytes, config.maxExecutions]) {
    if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("Invalid fake tool limit");
  }
  const scope = Object.freeze({ ...config.scope });
  const grants = new Set(config.grants);
  const tools = new Map([...config.tools].map(([id, tool]) => [id, { ...tool }]));
  const ledger = new Map<
    string,
    { fingerprint: string; outcome: Promise<PortOutcome<JsonValue>> }
  >();
  const denied = (code: string): PortOutcome<JsonValue> => ({
    status: "denied",
    error: {
      code,
      class: "policy",
      retryable: false,
      safeMessage: code,
      correlationId: scope.traceId,
    },
    evidence: [],
  });
  return {
    async invoke(request, options) {
      if (Object.keys(request).some((key) => !["toolId", "input", "idempotencyKey"].includes(key)))
        return denied("unknown_request_field");
      const tool = tools.get(request.toolId);
      if (!tool || !grants.has(request.toolId)) return denied("tool_not_granted");
      if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(request.idempotencyKey))
        return denied("invalid_idempotency_key");
      if (
        options.signal.aborted ||
        !Number.isFinite(options.deadline) ||
        options.deadline <= config.clock.now()
      )
        return denied("inactive_call");
      let encoded: string;
      try {
        encoded = encodeBoundedJson(request.input, config.maxInputBytes);
        if (
          encoded === undefined ||
          new TextEncoder().encode(encoded).byteLength > config.maxInputBytes
        )
          return denied("input_limit");
      } catch {
        return denied("invalid_input");
      }
      const fingerprint = JSON.stringify([request.toolId, encoded]);
      const previous = ledger.get(request.idempotencyKey);
      if (previous) {
        if (previous.fingerprint !== fingerprint) return denied("idempotency_conflict");
        return awaitFakeReplay(
          previous.outcome,
          options,
          { correlationId: scope.traceId, effect: tool.effect },
          config.clock,
        );
      }
      if (ledger.size >= config.maxExecutions) return denied("execution_limit");
      // Reserve synchronously before invoking the handler (including reentrant handlers).
      let resolve!: (outcome: PortOutcome<JsonValue>) => void;
      const outcome = new Promise<PortOutcome<JsonValue>>((done) => {
        resolve = done;
      });
      ledger.set(request.idempotencyKey, { fingerprint, outcome });
      void runFakeCall(
        (signal) => tool.execute(JSON.parse(encoded) as JsonValue, scope, signal),
        options,
        {
          maxOutputBytes: config.maxOutputBytes,
          correlationId: scope.traceId,
          effect: tool.effect,
        },
        config.clock,
      ).then(resolve);
      return structuredClone(await outcome);
    },
  };
}
