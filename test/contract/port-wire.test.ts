import { readFileSync } from "node:fs";
import { describe, expect, expectTypeOf, it } from "vitest";
import { type PortCallWire, PortCallWireSchema } from "../../src/contracts/generated/port-call.js";
import {
  type PortResultWire,
  PortResultWireSchema,
} from "../../src/contracts/generated/port-result.js";
import type {
  AgentPorts,
  ArtifactPort,
  MemoryItem,
  PortInput,
  PortMethod,
  PortOutcome,
  PortOutput,
} from "../../src/contracts/ports.js";
import { createPortWireCodec, PortWireError } from "../../src/testkit/port-wire.js";

const id = "id";
const evidence = {
  id,
  workspaceId: "w",
  runId: "r",
  attemptId: "a",
  fence: "1",
  policyRevision: "p",
  kind: "claim" as const,
  verification: "unverified" as const,
};
const pending = {
  id,
  workspaceId: "w",
  ownerRunId: "r",
  kind: "text",
  version: "1",
  status: "pending" as const,
};
const ready = { ...pending, status: "ready" as const, sha256: "a".repeat(64), bytes: 1 };
const memory: MemoryItem = {
  id,
  revision: "1",
  content: { text: "data" },
  trust: "untrusted",
  scope: "agent",
  audience: "internal",
  sensitivity: "private",
  expiresAt: null,
  provenance: [evidence],
};
const usage = {
  inputTokens: 1,
  outputTokens: 2,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  modelCalls: 1,
  toolCalls: 0,
  durationMs: 1,
  estimatedCostUsd: 0.01,
};
const fixtures = {
  "model.complete": {
    input: {
      profile: id,
      prompt: "hi",
      outputSchema: { type: "string" },
      contextRefs: [],
      idempotencyKey: id,
    },
    output: { output: "hello", usage, finishReason: "stop", providerRequestId: id },
  },
  "tools.invoke": {
    input: { toolId: id, input: { data: 1 }, idempotencyKey: id },
    output: { result: 1 },
  },
  "warehouse.catalog": { input: {}, output: [{ id, displayName: "Data" }] },
  "warehouse.describe": {
    input: { sourceId: id, datasetId: id },
    output: { columns: [{ name: "value", type: "number" }] },
  },
  "warehouse.query": {
    input: { queryId: id, parameters: { n: 1 }, maxRows: 1, maxBytes: 1024, idempotencyKey: id },
    output: { rows: [{ value: 1 }], truncated: false },
  },
  "artifacts.begin": {
    input: {
      kind: "text",
      version: "1",
      mediaType: "text/plain",
      expectedBytes: 1,
      expectedSha256: ready.sha256,
      idempotencyKey: id,
    },
    output: { uploadId: id, artifact: pending },
  },
  "artifacts.write": {
    input: { uploadId: id, offset: 0, bytesBase64: "YQ==", idempotencyKey: id },
    output: { acceptedBytes: 1 },
  },
  "artifacts.commit": { input: { uploadId: id, idempotencyKey: id }, output: ready },
  "artifacts.read": {
    input: { artifactId: id, offset: 0, maxBytes: 1 },
    output: { artifact: ready, bytesBase64: "YQ==", nextOffset: null },
  },
  "memory.read": { input: { id }, output: memory },
  "memory.search": {
    input: {
      query: "data",
      scope: "agent",
      limit: 1,
      maxBytes: 1024,
      asOf: "2026-09-27T00:00:00.000Z",
    },
    output: [memory],
  },
  "memory.remember": {
    input: {
      id,
      expectedRevision: null,
      content: memory.content,
      scope: "agent",
      audience: "internal",
      sensitivity: "private",
      expiresAt: null,
      provenance: [evidence],
      idempotencyKey: id,
    },
    output: memory,
  },
  "memory.forget": {
    input: { id, expectedRevision: "1", idempotencyKey: id },
    output: { revision: "2", deleted: true },
  },
  "collaboration.discover": {
    input: { capability: id, limit: 1 },
    output: [{ agentId: id, version: "1", capabilities: [id] }],
  },
  "collaboration.invoke": {
    input: { agentId: id, version: "1", input: null, idempotencyKey: id },
    output: { runId: id },
  },
  "collaboration.wait": { input: { runIds: [id] }, output: { completedRunIds: [id] } },
  "collaboration.result": {
    input: { runId: id },
    output: { status: "completed", output: {}, artifacts: [ready] },
  },
  "sandbox.execute": {
    input: {
      commandId: id,
      arguments: {},
      inputArtifacts: [id],
      credentialRefs: [id],
      maxOutputBytes: 1024,
      idempotencyKey: id,
    },
    output: { executionId: id, exitCode: null, artifacts: [] },
  },
  "sandbox.pause": { input: { executionId: id, idempotencyKey: id }, output: { checkpointId: id } },
  "sandbox.resume": {
    input: { checkpointId: id, idempotencyKey: id },
    output: { executionId: id },
  },
} satisfies { [M in PortMethod]: { input: PortInput<M>; output: PortOutput<M> } };
const codec = createPortWireCodec();
const call = (method: PortMethod) => ({
  apiVersion: "port-call.v1",
  callId: "call",
  method,
  deadline: 1000,
  input: fixtures[method].input,
});
const result = (method: PortMethod) => ({
  apiVersion: "port-result.v1",
  callId: "call",
  method,
  outcome: { status: "ok", output: fixtures[method].output, evidence: [evidence], limitations: [] },
});

describe("canonical port wire methods", () => {
  for (const method of Object.keys(fixtures) as PortMethod[]) {
    it(`${method}: validates request/result roundtrip and rejects forged control fields`, () => {
      const request = call(method);
      const response = result(method);
      const encoded = codec.encodeCall(request);
      expect(codec.decodeCall(new TextEncoder().encode(encoded))).toEqual(request);
      expect(codec.decodeResult(codec.encodeResult(response, request), request)).toEqual(response);
      expect(() => codec.encodeCall({ ...request, workspaceId: "other" })).toThrow(
        "invalid_contract",
      );
      expect(() =>
        codec.encodeCall({ ...request, input: { ...request.input, tenantId: "other" } }),
      ).toThrow("invalid_contract");
      expect(() => codec.encodeCall({ ...request, input: undefined })).toThrow("invalid_frame");
      expect(() => codec.encodeResult({ ...response, actorId: "other" }, request)).toThrow(
        "invalid_contract",
      );
      expect(() =>
        codec.encodeResult(
          { ...response, outcome: { ...response.outcome, secret: "hidden" } },
          request,
        ),
      ).toThrow("invalid_contract");
    });
    it(`${method}: preserves all non-success outcomes and forbids retryable unknown`, () => {
      const request = call(method);
      const error = {
        code: "denied",
        class: "policy",
        retryable: false,
        safeMessage: "Denied",
        correlationId: "trace",
      };
      const outcomes = [
        { status: "queued", operationId: id, evidence: [] },
        ...["needs_approval", "needs_input"].map((status) => ({
          status,
          requestId: id,
          safeMessage: "Waiting",
        })),
        ...["denied", "failed"].map((status) => ({ status, error, evidence: [] })),
        { status: "unknown", error: { ...error, class: "unknown" }, evidence: [] },
      ];
      for (const outcome of outcomes) {
        const response = { ...result(method), outcome };
        expect(codec.decodeResult(codec.encodeResult(response, request), request)).toEqual(
          response,
        );
      }
      expect(() =>
        codec.encodeResult(
          { ...result(method), outcome: { status: "unknown", error, evidence: [] } },
          request,
        ),
      ).toThrow("invalid_contract");
      expect(() =>
        codec.encodeResult(
          {
            ...result(method),
            outcome: {
              status: "unknown",
              error: { ...error, class: "unknown", retryable: true },
              evidence: [],
            },
          },
          request,
        ),
      ).toThrow("invalid_contract");
    });
  }
});
it("rejects wrong versions, mismatched methods and uncorrelated responses", () => {
  const request = call("memory.read");
  expect(() => codec.encodeCall({ ...request, apiVersion: "port-call.v2" })).toThrow(
    "invalid_contract",
  );
  expect(() => codec.encodeCall({ ...request, method: "tools.invoke" })).toThrow(
    "invalid_contract",
  );
  expect(() => codec.encodeCall({ ...request, method: "process.exec" })).toThrow(
    "invalid_contract",
  );
  expect(() =>
    codec.encodeResult(result("memory.read"), { ...request, callId: "different" }),
  ).toThrow("correlation_mismatch");
  expect(() =>
    codec.encodeResult(result("memory.read"), { ...request, method: "tools.invoke" }),
  ).toThrow("correlation_mismatch");
  expect(() =>
    codec.encodeResult({ ...result("memory.read"), apiVersion: "port-result.v2" }, request),
  ).toThrow("invalid_contract");
});
it("uses bounded canonical base64 for bytes, including empty data and every byte value", () => {
  for (const length of [0, 1, 2, 3, 256, 1024 * 1024]) {
    const bytes = Uint8Array.from({ length }, (_, index) => index % 256);
    const decoded = codec.decodeBytes(codec.encodeBytes(bytes));
    expect(decoded.byteLength).toBe(bytes.byteLength);
    expect(Buffer.compare(Buffer.from(decoded), Buffer.from(bytes))).toBe(0);
  }
  for (const invalid of ["a", "AA", "AA=", "AA===", "AB==", "AAB=", "__8=", "AA==\n", "===="]) {
    expect(() => codec.decodeBytes(invalid)).toThrow(PortWireError);
    const request = call("artifacts.write");
    expect(() =>
      codec.encodeCall({ ...request, input: { ...request.input, bytesBase64: invalid } }),
    ).toThrow(PortWireError);
    const response = result("artifacts.read");
    expect(() =>
      codec.encodeResult(
        {
          ...response,
          outcome: {
            ...response.outcome,
            output: { ...fixtures["artifacts.read"].output, bytesBase64: invalid },
          },
        },
        call("artifacts.read"),
      ),
    ).toThrow(PortWireError);
  }
  const request = call("artifacts.write");
  const large = codec.encodeBytes(new Uint8Array(1024 * 1024));
  expect(
    codec.decodeCall(
      codec.encodeCall({ ...request, input: { ...request.input, bytesBase64: large } }),
    ).method,
  ).toBe("artifacts.write");
});
it("caps aggregate UTF-8 bytes/depth before schema traversal and redacts invalid frame details", () => {
  const bounded = createPortWireCodec({ maxBytes: 512, maxDepth: 8 });
  expect(() =>
    bounded.encodeCall({
      ...call("tools.invoke"),
      input: { toolId: id, input: "é".repeat(300), idempotencyKey: id },
    }),
  ).toThrow("payload_limit");
  let nested: unknown = null;
  for (let i = 0; i < 20; i++) nested = { nested };
  expect(() =>
    bounded.decodeCall(
      JSON.stringify({
        ...call("tools.invoke"),
        input: { toolId: id, input: nested, idempotencyKey: id },
      }),
    ),
  ).toThrow("payload_limit");
  expect(() => bounded.decodeCall(" ".repeat(513))).toThrow("payload_limit");
  expect(() => bounded.encodeBytes(new Uint8Array(512))).toThrow("payload_limit");
  expect(() => bounded.decodeBytes("A".repeat(516))).toThrow("payload_limit");
  expect(() => bounded.decodeCall(new Uint8Array([0xc0, 0xaf]))).toThrow("invalid_frame");
  expect(() => bounded.decodeCall("{secret-provider-detail")).toThrow(/^invalid_frame$/);
  expect(() => createPortWireCodec({ maxBytes: 16777217 })).toThrow("Invalid wire limits");
  expect(() => createPortWireCodec({ maxDepth: 65 })).toThrow("Invalid wire limits");
});
it("validates strict memory trust, retention and artifact states", () => {
  const remember = call("memory.remember");
  expect(() =>
    codec.encodeCall({ ...remember, input: { ...remember.input, expiresAt: "tomorrow" } }),
  ).toThrow("invalid_contract");
  expect(() =>
    codec.encodeResult(
      {
        ...result("memory.read"),
        outcome: {
          status: "ok",
          output: { ...memory, trust: "trusted" },
          evidence: [],
          limitations: [],
        },
      },
      call("memory.read"),
    ),
  ).toThrow("invalid_contract");
  expect(() =>
    codec.encodeResult(
      {
        ...result("artifacts.commit"),
        outcome: { status: "ok", output: pending, evidence: [], limitations: [] },
      },
      call("artifacts.commit"),
    ),
  ).toThrow("invalid_contract");
  expect(() =>
    codec.encodeCall({
      ...call("warehouse.query"),
      input: { ...fixtures["warehouse.query"].input, maxRows: 0 },
    }),
  ).toThrow("invalid_contract");
  expect(
    codec.decodeResult(
      codec.encodeResult(
        {
          ...result("memory.read"),
          outcome: { status: "ok", output: null, evidence: [], limitations: [] },
        },
        call("memory.read"),
      ),
      call("memory.read"),
    ),
  ).toMatchObject({ outcome: { output: null } });
});
it("keeps embedded shared schema definitions identical to their canonical source", () => {
  const names = {
    Evidence: "evidence-ref",
    Artifact: "artifact-ref",
    Usage: "usage-summary",
    Error: "structured-error",
  };
  for (const schema of [PortCallWireSchema, PortResultWireSchema]) {
    for (const [definition, filename] of Object.entries(names)) {
      const defs = schema.$defs as Record<string, unknown>;
      if (!(definition in defs)) continue;
      const source = JSON.parse(readFileSync(`schemas/${filename}.schema.json`, "utf8"));
      delete source.$schema;
      delete source.$id;
      delete source.title;
      expect(defs[definition]).toEqual(source);
    }
    const manifest = JSON.parse(readFileSync("schemas/agent-manifest.schema.json", "utf8"));
    expect(schema.$defs.Json).toEqual(manifest.$defs.Json);
  }
  expect(PortCallWireSchema.oneOf.map((entry) => entry.properties.method.const).sort()).toEqual(
    Object.keys(fixtures).sort(),
  );
  expect(PortResultWireSchema.oneOf.map((entry) => entry.properties.method.const).sort()).toEqual(
    Object.keys(fixtures).sort(),
  );
});
it("derives in-process JSON signatures from wire types and substitutes bytes explicitly", () => {
  type NativeInput<M extends PortMethod> =
    M extends `${infer P extends keyof AgentPorts}.${infer Op}`
      ? Op extends keyof NonNullable<AgentPorts[P]>
        ? NonNullable<AgentPorts[P]>[Op] extends (input: infer I, ...rest: never[]) => unknown
          ? I
          : never
        : never
      : never;
  expectTypeOf<NativeInput<"memory.remember">>().toEqualTypeOf<PortInput<"memory.remember">>();
  expectTypeOf<Awaited<ReturnType<AgentPorts["model"]["complete"]>>>().toEqualTypeOf<
    PortOutcome<PortOutput<"model.complete">>
  >();
  expectTypeOf<Parameters<ArtifactPort["write"]>[0]>().toEqualTypeOf<
    Omit<PortInput<"artifacts.write">, "bytesBase64"> & { bytes: Uint8Array }
  >();
  expectTypeOf<PortMethod>().toEqualTypeOf<PortCallWire["method"]>();
  expectTypeOf<PortMethod>().toEqualTypeOf<PortResultWire["method"]>();
});
