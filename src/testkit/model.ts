import { Ajv2020 } from "ajv/dist/2020.js";
import type { JsonValue, ModelPort, PortOutcome, UsageSummary } from "../contracts/index.js";
import { awaitFakeReplay, runFakeCall, type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";

type ModelOutput = {
  output: JsonValue;
  usage: UsageSummary;
  finishReason: "stop" | "length" | "tool_call" | "refusal";
  providerRequestId: string;
};
export function createFakeModelPort(config: {
  profiles: readonly string[];
  clock: TestClock;
  maxInputBytes: number;
  maxOutputBytes: number;
  maxCalls: number;
  respond(input: Parameters<ModelPort["complete"]>[0], signal: AbortSignal): Promise<JsonValue>;
}): ModelPort {
  for (const value of [config.maxInputBytes, config.maxOutputBytes, config.maxCalls])
    if (!Number.isSafeInteger(value) || value < 1) throw new Error("Invalid fake model limits");
  const profiles = new Set(config.profiles);
  const ledger = new Map<
    string,
    { fingerprint: string; result: Promise<PortOutcome<ModelOutput>> }
  >();
  const failure = (code: string, denied = false): PortOutcome<ModelOutput> => ({
    status: denied ? "denied" : "failed",
    error: {
      code,
      class: denied ? "policy" : "validation",
      retryable: false,
      safeMessage: code,
      correlationId: "fake-model",
    },
    evidence: [],
  });
  return {
    async complete(request, options) {
      if (!profiles.has(request.profile)) return failure("profile_not_granted", true);
      if (
        options.signal.aborted ||
        !Number.isFinite(options.deadline) ||
        options.deadline <= config.clock.now()
      )
        return failure("inactive_call");
      if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(request.idempotencyKey))
        return failure("invalid_idempotency_key");
      let fingerprint: string;
      let input: typeof request;
      let validate: ReturnType<Ajv2020["compile"]>;
      try {
        fingerprint = encodeBoundedJson(request, config.maxInputBytes);
        input = JSON.parse(fingerprint) as typeof request;
        if (
          Object.keys(input).some(
            (key) =>
              !["profile", "prompt", "outputSchema", "contextRefs", "idempotencyKey"].includes(key),
          ) ||
          typeof input.prompt !== "string" ||
          !Array.isArray(input.contextRefs) ||
          input.contextRefs.some((ref) => typeof ref !== "string")
        )
          return failure("invalid_request");
        // No loadSchema callback: unresolved/remote references fail offline.
        validate = new Ajv2020({ strict: true, addUsedSchema: false }).compile(input.outputSchema);
      } catch {
        return failure("invalid_request_or_schema");
      }
      const prior = ledger.get(input.idempotencyKey);
      if (prior)
        return prior.fingerprint === fingerprint
          ? awaitFakeReplay(
              prior.result,
              options,
              { correlationId: "fake-model", effect: "read" },
              config.clock,
            )
          : failure("idempotency_conflict");
      if (ledger.size >= config.maxCalls) return failure("model_call_limit", true);
      const sequence = ledger.size + 1;
      let settle!: (result: PortOutcome<ModelOutput>) => void;
      const result = new Promise<PortOutcome<ModelOutput>>((resolve) => {
        settle = resolve;
      });
      ledger.set(input.idempotencyKey, { fingerprint, result });
      void runFakeCall(
        (signal) => config.respond(input, signal),
        options,
        { maxOutputBytes: config.maxOutputBytes, correlationId: "fake-model", effect: "read" },
        config.clock,
      ).then((outcome) => {
        if (outcome.status !== "ok") {
          settle(outcome);
          return;
        }
        if (!validate(outcome.output)) {
          settle(failure("model_output_schema"));
          return;
        }
        settle({
          ...outcome,
          output: {
            output: outcome.output,
            usage: {
              inputTokens: 0,
              outputTokens: 0,
              cacheReadTokens: 0,
              cacheWriteTokens: 0,
              modelCalls: 1,
              toolCalls: 0,
              durationMs: 0,
              estimatedCostUsd: 0,
            },
            finishReason: "stop",
            providerRequestId: `fake-model-${sequence}`,
          },
          limitations: ["Scripted model fixture; token/cost counters are synthetic zeros"],
        });
      });
      return structuredClone(await result);
    },
  };
}
