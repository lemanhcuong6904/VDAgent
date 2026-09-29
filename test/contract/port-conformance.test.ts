/**
 * M1.6 conformance matrix: every fake port faces the same timeout, cancellation, scope,
 * output/byte-limit and unknown-field cases. Per-port suites keep port-specific semantics.
 */
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import type { AgentScope, CallOptions, PortOutcome } from "../../src/contracts/index.js";
import { createFakeArtifactPort } from "../../src/testkit/artifacts.js";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeCollaborationPort } from "../../src/testkit/collaboration.js";
import { createFakeMemoryPort } from "../../src/testkit/memory.js";
import { createFakeModelPort } from "../../src/testkit/model.js";
import { createFakeSandboxPort } from "../../src/testkit/sandbox.js";
import { createFakeToolPort } from "../../src/testkit/tools.js";
import { createFakeWarehousePort } from "../../src/testkit/warehouse.js";

type Variant = "valid" | "unknownField" | "outOfScope" | "oversized";
interface Harness {
  /** Effect class decides whether interruption after dispatch must stay `unknown`. */
  effect: "read" | "write";
  /** Artifacts cannot prove a foreign ID is absent, so they answer `unknown` after lookup. */
  scopeMiss?: "unknown";
  dispatched(): number;
  release(): void;
  call(variant: Variant, options: CallOptions): Promise<PortOutcome<unknown>>;
}
type Factory = (clock: ManualClock, block: boolean) => Harness;

const scope: AgentScope = {
  tenantId: "t",
  workspaceId: "w",
  actorId: "a",
  audience: "internal",
  taskId: "task",
  runId: "r",
  attemptId: "attempt",
  agentId: "agent",
  agentVersion: "1.0.0",
  policyRevision: "p",
  fence: "1",
  traceId: "trace",
};

function gate() {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}
const big = "x".repeat(2000);
const loose = (value: object) => value as never; // Deliberately violates the static request type.

const ports: Record<string, Factory> = {
  model(clock, block) {
    let count = 0;
    const hold = gate();
    const port = createFakeModelPort({
      profiles: ["fixture"],
      clock,
      maxInputBytes: 4096,
      maxOutputBytes: 256,
      maxCalls: 4,
      respond: async (input) => {
        count++;
        if (block) await hold.promise;
        return input.prompt === "big" ? big : "answer";
      },
    });
    return {
      effect: "read",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        const request = {
          profile: variant === "outOfScope" ? "ungranted" : "fixture",
          prompt: variant === "oversized" ? "big" : "question",
          outputSchema: { type: "string" },
          contextRefs: [],
          idempotencyKey: "model",
        };
        return port.complete(
          variant === "unknownField" ? loose({ ...request, extra: 1 }) : request,
          options,
        );
      },
    };
  },
  tools(clock, block) {
    let count = 0;
    const hold = gate();
    const execute = async (input: unknown) => {
      count++;
      if (block) await hold.promise;
      return (input as { big?: boolean }).big ? big : "done";
    };
    const port = createFakeToolPort({
      scope,
      grants: ["write"],
      tools: new Map([
        ["write", { effect: "write", execute }],
        ["hidden", { effect: "write", execute }],
      ]),
      clock,
      maxInputBytes: 4096,
      maxOutputBytes: 256,
      maxExecutions: 4,
    });
    return {
      effect: "write",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        const request = {
          toolId: variant === "outOfScope" ? "hidden" : "write",
          input: { big: variant === "oversized" },
          idempotencyKey: "tool",
        };
        return port.invoke(
          variant === "unknownField" ? loose({ ...request, extra: 1 }) : request,
          options,
        );
      },
    };
  },
  warehouse(clock, block) {
    let count = 0;
    const hold = gate();
    const port = createFakeWarehousePort({
      fixtures: [
        {
          sourceId: "s",
          displayName: "Source",
          datasetId: "d",
          columns: [{ name: "v", type: "string" }],
          queryId: "q",
          rows: [],
        },
      ],
      handlers: new Map([
        [
          "q",
          {
            parameterSchema: {
              type: "object",
              properties: { big: { type: "boolean" } },
              required: ["big"],
              additionalProperties: false,
            },
            execute: async (parameters) => {
              count++;
              if (block) await hold.promise;
              return parameters.big ? [{ v: big }] : [{ v: "row" }];
            },
          },
        ],
      ]),
      clock,
      maxRows: 10,
      maxBytes: 1024,
      maxInputBytes: 4096,
    });
    return {
      effect: "read",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        const request = {
          queryId: variant === "outOfScope" ? "unregistered" : "q",
          parameters: { big: variant === "oversized" },
          maxRows: 10,
          maxBytes: 1024,
          idempotencyKey: "query",
        };
        return port.query(
          variant === "unknownField" ? loose({ ...request, sql: "select 1" }) : request,
          options,
        );
      },
    };
  },
  memory(clock, block) {
    let count = 0;
    const hold = gate();
    const port = createFakeMemoryPort({
      workspaceId: "w",
      audience: "internal",
      scopes: ["agent"],
      sensitivities: ["private"],
      clock,
      maxBytes: 1024,
      maxItems: 4,
      maxMutations: 4,
      before: async () => {
        count++;
        if (block) await hold.promise;
      },
    });
    return {
      effect: "write",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        const request = {
          id: "note",
          expectedRevision: null,
          content: { text: variant === "oversized" ? big : "fact" },
          scope: variant === "outOfScope" ? ("workspace" as const) : ("agent" as const),
          audience: "internal",
          sensitivity: "private" as const,
          expiresAt: null,
          provenance: [],
          idempotencyKey: "remember",
        };
        return port.remember(
          variant === "unknownField" ? loose({ ...request, extra: 1 }) : request,
          options,
        );
      },
    };
  },
  artifacts(clock, block) {
    let count = 0;
    const hold = gate();
    const port = createFakeArtifactPort({
      workspaceId: "w",
      ownerRunId: "r",
      clock,
      maxArtifactBytes: 1024,
      maxTotalBytes: 1024,
      maxUploads: 4,
      maxMutations: 4,
      maxRequestBytes: 4096,
      maxResponseBytes: 4096,
      before: async () => {
        count++;
        if (block) await hold.promise;
      },
    });
    const bytes = new TextEncoder().encode("artifact");
    return {
      effect: "write",
      scopeMiss: "unknown",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        if (variant === "outOfScope")
          return port.read({ artifactId: "foreign-artifact", offset: 0, maxBytes: 64 }, options);
        const request = {
          kind: "text",
          version: "1",
          mediaType: "text/plain",
          expectedBytes: variant === "oversized" ? 4096 : bytes.length,
          expectedSha256: createHash("sha256").update(bytes).digest("hex"),
          idempotencyKey: "begin",
        };
        return port.begin(
          variant === "unknownField" ? loose({ ...request, extra: 1 }) : request,
          options,
        );
      },
    };
  },
  collaboration(clock, block) {
    let count = 0;
    const hold = gate();
    const port = createFakeCollaborationPort({
      fixtures: [
        {
          agentId: "child",
          version: "1.0.0",
          capabilities: ["analyze"],
          output: { n: 1 },
          status: "completed",
        },
      ],
      clock,
      maxBytes: 1024,
      maxRuns: 4,
      before: async () => {
        count++;
        if (block) await hold.promise;
      },
    });
    return {
      effect: "write",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        const request = {
          agentId: variant === "outOfScope" ? "stranger" : "child",
          version: "1.0.0",
          input: { text: variant === "oversized" ? big : "" },
          idempotencyKey: "child",
        };
        return port.invoke(
          variant === "unknownField" ? loose({ ...request, extra: 1 }) : request,
          options,
        );
      },
    };
  },
  sandbox(clock, block) {
    let count = 0;
    const hold = gate();
    const port = createFakeSandboxPort({
      scope,
      clock,
      commands: [
        {
          commandId: "analyze",
          argumentSchema: {
            type: "object",
            properties: { big: { type: "boolean" } },
            required: ["big"],
            additionalProperties: false,
          },
          artifacts: [],
          run: async (arguments_) => {
            count++;
            if (block) await hold.promise;
            return { exitCode: 0, output: (arguments_ as { big: boolean }).big ? big : "ok" };
          },
        },
      ],
      inputArtifacts: [],
      credentialRefs: [],
      maxInstances: 4,
      maxMutations: 4,
      maxInputBytes: 4096,
      maxOutputBytes: 4096,
    });
    return {
      effect: "write",
      dispatched: () => count,
      release: hold.release,
      call(variant, options) {
        const request = {
          commandId: "analyze",
          arguments: { big: variant === "oversized" },
          inputArtifacts: [],
          credentialRefs: variant === "outOfScope" ? ["vault:ungranted"] : [],
          maxOutputBytes: 64,
          idempotencyKey: "execute",
        };
        return port.execute(
          variant === "unknownField" ? loose({ ...request, extra: 1 }) : request,
          options,
        );
      },
    };
  },
};

const live = (deadline = 1000) => ({ signal: new AbortController().signal, deadline });
async function untilDispatched(harness: Harness) {
  for (let turn = 0; turn < 50 && harness.dispatched() === 0; turn++)
    await new Promise((resolve) => setImmediate(resolve));
  expect(harness.dispatched()).toBe(1);
}
const interrupted = (effect: Harness["effect"]) => (effect === "write" ? "unknown" : "failed");

describe.each(Object.entries(ports))("%s port conformance", (_name, factory) => {
  it("succeeds for the valid baseline so negative cases are meaningful", async () => {
    const clock = new ManualClock();
    const harness = factory(clock, false);
    const outcome = await harness.call("valid", live());
    expect(outcome.status).toBe("ok");
    expect(clock.pendingTimers).toBe(0);
  });

  it("rejects an expired deadline before dispatch", async () => {
    const clock = new ManualClock(5000);
    const harness = factory(clock, false);
    expect((await harness.call("valid", live(5000))).status).not.toBe("ok");
    expect(harness.dispatched()).toBe(0);
  });

  it("rejects an already-cancelled call before dispatch", async () => {
    const clock = new ManualClock();
    const harness = factory(clock, false);
    const controller = new AbortController();
    controller.abort();
    const outcome = await harness.call("valid", { signal: controller.signal, deadline: 1000 });
    expect(outcome.status).not.toBe("ok");
    expect(harness.dispatched()).toBe(0);
  });

  it("settles cancellation after dispatch without a late success", async () => {
    const clock = new ManualClock();
    const harness = factory(clock, true);
    const controller = new AbortController();
    const pending = harness.call("valid", { signal: controller.signal, deadline: 1000 });
    await untilDispatched(harness);
    controller.abort();
    const outcome = await pending;
    harness.release();
    await new Promise((resolve) => setImmediate(resolve));
    expect(outcome.status).toBe(interrupted(harness.effect));
    expect(clock.pendingTimers).toBe(0);
  });

  it("settles a deadline reached after dispatch without a late success", async () => {
    const clock = new ManualClock();
    const harness = factory(clock, true);
    const pending = harness.call("valid", live(100));
    await untilDispatched(harness);
    clock.advance(100);
    const outcome = await pending;
    harness.release();
    expect(outcome.status).toBe(interrupted(harness.effect));
    expect(clock.pendingTimers).toBe(0);
  });

  it("rejects unknown request fields before dispatch", async () => {
    const harness = factory(new ManualClock(), false);
    expect((await harness.call("unknownField", live())).status).not.toBe("ok");
    expect(harness.dispatched()).toBe(0);
  });

  it("rejects out-of-scope or ungranted targets without success", async () => {
    const harness = factory(new ManualClock(), false);
    const outcome = await harness.call("outOfScope", live());
    if (harness.scopeMiss) {
      expect(outcome.status).toBe(harness.scopeMiss);
      return;
    }
    expect(["denied", "failed"]).toContain(outcome.status);
    expect(harness.dispatched()).toBe(0);
  });

  it("never returns ok for data above the configured byte limit", async () => {
    const clock = new ManualClock();
    const harness = factory(clock, false);
    expect((await harness.call("oversized", live())).status).not.toBe("ok");
    expect(clock.pendingTimers).toBe(0);
  });
});
