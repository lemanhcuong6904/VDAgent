import type { CallOptions, CollaborationPort, JsonValue, PortOutcome } from "../contracts/index.js";
import { awaitFakeReplay, runFakeCall, type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";

export interface CollaborationFixture {
  agentId: string;
  version: string;
  capabilities: string[];
  output: JsonValue;
  status: "running" | "waiting" | "completed" | "failed" | "cancelled";
}

/** An instance represents one host-selected scope and its granted agent versions. */
export function createFakeCollaborationPort(config: {
  fixtures: CollaborationFixture[];
  clock: TestClock;
  maxBytes: number;
  maxRuns: number;
  before?: (
    operation: "discover" | "invoke" | "wait" | "result",
    signal: AbortSignal,
  ) => Promise<void>;
}): CollaborationPort {
  const { clock, maxBytes, maxRuns, before } = config;
  for (const value of [maxBytes, maxRuns])
    if (!Number.isSafeInteger(value) || value < 1) throw new Error("Invalid collaboration limits");
  const fixtures = JSON.parse(
    encodeBoundedJson(config.fixtures, maxBytes),
  ) as CollaborationFixture[];
  const key = (id: string, version: string) => JSON.stringify([id, version]);
  const agents = new Map(
    fixtures.map((fixture) => [key(fixture.agentId, fixture.version), fixture]),
  );
  if (agents.size !== fixtures.length) throw new Error("Duplicate agent fixture");
  const runs = new Map<string, CollaborationFixture>();
  const invocations = new Map<
    string,
    { fingerprint: string; outcome: Promise<PortOutcome<{ runId: string }>> }
  >();
  const denied = <T>(code: string): PortOutcome<T> => ({
    status: "denied",
    error: {
      code,
      class: "policy",
      retryable: false,
      safeMessage: code,
      correlationId: "fake-collaboration",
    },
    evidence: [],
  });
  const limits = {
    maxOutputBytes: maxBytes,
    correlationId: "fake-collaboration",
    effect: "read" as const,
  };
  function snapshot<T>(input: T, fields: string[]): T | null {
    try {
      const value = JSON.parse(encodeBoundedJson(input, maxBytes));
      if (
        !value ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        Object.keys(value).length !== fields.length ||
        fields.some((field) => !Object.hasOwn(value, field))
      )
        return null;
      return value as T;
    } catch {
      return null;
    }
  }
  function call<T>(
    operation: "discover" | "invoke" | "wait" | "result",
    execute: () => T,
    options: CallOptions,
  ): Promise<PortOutcome<T>> {
    return runFakeCall(
      async (signal) => {
        if (before) await before(operation, signal);
        if (signal.aborted) throw new Error("inactive_call");
        return execute();
      },
      options,
      { ...limits, effect: operation === "invoke" ? "write" : "read" },
      clock,
    );
  }
  return {
    discover(input, options) {
      const value = snapshot(input, ["capability", "limit"]);
      if (
        !value ||
        typeof value.capability !== "string" ||
        !Number.isSafeInteger(value.limit) ||
        value.limit < 1 ||
        value.limit > maxRuns
      )
        return Promise.resolve(denied("invalid_discovery"));
      return call(
        "discover",
        () =>
          fixtures
            .filter((fixture) => fixture.capabilities.includes(value.capability))
            .slice(0, value.limit)
            .map(({ agentId, version, capabilities }) => ({ agentId, version, capabilities })),
        options,
      );
    },
    invoke(input, options) {
      const value = snapshot(input, ["agentId", "version", "input", "idempotencyKey"]);
      if (
        !value ||
        typeof value.idempotencyKey !== "string" ||
        !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.idempotencyKey) ||
        !("input" in value)
      )
        return Promise.resolve(denied("invalid_invocation"));
      const agent = agents.get(key(value.agentId, value.version));
      if (!agent) return Promise.resolve(denied("agent_not_granted"));
      const fingerprint = canonical(value);
      if (
        options.signal.aborted ||
        !Number.isFinite(options.deadline) ||
        options.deadline <= clock.now()
      )
        return runFakeCall(
          async () => ({ runId: "" }),
          options,
          { ...limits, effect: "write" },
          clock,
        );
      const previous = invocations.get(value.idempotencyKey);
      if (previous) {
        if (previous.fingerprint !== fingerprint)
          return Promise.resolve(denied("idempotency_conflict"));
        return awaitFakeReplay(
          previous.outcome,
          options,
          { correlationId: limits.correlationId, effect: "write" },
          clock,
        );
      }
      if (invocations.size >= maxRuns) return Promise.resolve(denied("run_limit"));
      let resolve!: (value: PortOutcome<{ runId: string }>) => void;
      const outcome = new Promise<PortOutcome<{ runId: string }>>((done) => {
        resolve = done;
      });
      invocations.set(value.idempotencyKey, { fingerprint, outcome });
      void call(
        "invoke",
        () => {
          const runId = `fake-child-${runs.size + 1}`;
          runs.set(runId, agent);
          return { runId };
        },
        options,
      ).then(resolve);
      return outcome.then((result) => structuredClone(result));
    },
    wait(input, options) {
      const value = snapshot(input, ["runIds"]);
      if (
        !value ||
        !Array.isArray(value.runIds) ||
        value.runIds.length > maxRuns ||
        value.runIds.some((id) => typeof id !== "string" || !runs.has(id))
      )
        return Promise.resolve(denied("run_unavailable"));
      return call(
        "wait",
        () => ({
          completedRunIds: [...new Set(value.runIds)].filter(
            (id) => runs.get(id)?.status === "completed",
          ),
        }),
        options,
      );
    },
    result(input, options) {
      const value = snapshot(input, ["runId"]);
      const run = value && runs.get(value.runId);
      if (!run) return Promise.resolve(denied("run_unavailable"));
      return call(
        "result",
        () => ({
          status: run.status,
          ...(run.status === "completed" ? { output: run.output } : {}),
          artifacts: [],
        }),
        options,
      );
    },
  };
}

function canonical(value: JsonValue): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
