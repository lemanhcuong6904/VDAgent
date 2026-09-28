import { createHash } from "node:crypto";
import { expect, it } from "vitest";
import type { AgentScope } from "../../src/contracts/index.js";
import type { PortInput, PortMethod, PortOutcome } from "../../src/contracts/ports.js";
import { createFakeArtifactPort } from "../../src/testkit/artifacts.js";
import { ManualClock } from "../../src/testkit/call.js";
import { createFakeCollaborationPort } from "../../src/testkit/collaboration.js";
import { createFakeMemoryPort } from "../../src/testkit/memory.js";
import { createFakeModelPort } from "../../src/testkit/model.js";
import { createPortWireCodec } from "../../src/testkit/port-wire.js";
import { createFakeSandboxPort } from "../../src/testkit/sandbox.js";
import { createFakeToolPort } from "../../src/testkit/tools.js";
import { createFakeWarehousePort } from "../../src/testkit/warehouse.js";

it("validates real fake-port lifecycle results for every wire method", async () => {
  const clock = new ManualClock();
  const options = { signal: new AbortController().signal, deadline: 1000 };
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
  const codec = createPortWireCodec();
  const methods = new Set<PortMethod>();
  function check<M extends PortMethod, T>(
    method: M,
    input: PortInput<M>,
    outcome: PortOutcome<T>,
  ): T {
    methods.add(method);
    const request = {
      apiVersion: "port-call.v1",
      callId: `call-${methods.size}`,
      method,
      deadline: options.deadline,
      input,
    };
    expect(codec.decodeCall(codec.encodeCall(request))).toEqual(request);
    const response = { apiVersion: "port-result.v1", callId: request.callId, method, outcome };
    expect(codec.decodeResult(codec.encodeResult(response, request), request)).toEqual(response);
    if (outcome.status !== "ok") throw new Error(`Expected fixture success for ${method}`);
    return outcome.output;
  }
  const model = createFakeModelPort({
    profiles: ["fixture"],
    clock,
    maxInputBytes: 4096,
    maxOutputBytes: 4096,
    maxCalls: 1,
    respond: async () => "answer",
  });
  const modelInput = {
    profile: "fixture",
    prompt: "question",
    outputSchema: { type: "string" },
    contextRefs: [],
    idempotencyKey: "model",
  };
  check("model.complete", modelInput, await model.complete(modelInput, options));
  const tool = createFakeToolPort({
    scope,
    grants: ["echo"],
    tools: new Map([["echo", { effect: "read", execute: async (input) => input }]]),
    clock,
    maxInputBytes: 4096,
    maxOutputBytes: 4096,
    maxExecutions: 1,
  });
  const toolInput = { toolId: "echo", input: { n: 1 }, idempotencyKey: "tool" };
  check("tools.invoke", toolInput, await tool.invoke(toolInput, options));
  const warehouse = createFakeWarehousePort({
    fixtures: [
      {
        sourceId: "s",
        displayName: "Source",
        datasetId: "d",
        columns: [{ name: "n", type: "number" }],
        queryId: "q",
        rows: [{ n: 1 }],
      },
    ],
    clock,
    maxRows: 10,
    maxBytes: 4096,
    maxInputBytes: 4096,
  });
  check("warehouse.catalog", {}, await warehouse.catalog(options));
  const describe = { sourceId: "s", datasetId: "d" };
  check("warehouse.describe", describe, await warehouse.describe(describe, options));
  const query = {
    queryId: "q",
    parameters: {},
    maxRows: 1,
    maxBytes: 4096,
    idempotencyKey: "query",
  };
  check("warehouse.query", query, await warehouse.query(query, options));
  const artifacts = createFakeArtifactPort({
    workspaceId: "w",
    ownerRunId: "r",
    clock,
    maxArtifactBytes: 4096,
    maxTotalBytes: 4096,
    maxUploads: 1,
    maxMutations: 3,
    maxRequestBytes: 4096,
    maxResponseBytes: 4096,
  });
  const bytes = new TextEncoder().encode("Dữ liệu");
  const beginInput = {
    kind: "text",
    version: "1",
    mediaType: "text/plain",
    expectedBytes: bytes.length,
    expectedSha256: createHash("sha256").update(bytes).digest("hex"),
    idempotencyKey: "begin",
  };
  const upload = check("artifacts.begin", beginInput, await artifacts.begin(beginInput, options));
  const write = { uploadId: upload.uploadId, offset: 0, bytes, idempotencyKey: "write" };
  const { bytes: raw, ...writeMetadata } = write;
  check(
    "artifacts.write",
    { ...writeMetadata, bytesBase64: codec.encodeBytes(raw) },
    await artifacts.write(write, options),
  );
  const commit = { uploadId: upload.uploadId, idempotencyKey: "commit" };
  const artifact = check("artifacts.commit", commit, await artifacts.commit(commit, options));
  const read = { artifactId: artifact.id, offset: 0, maxBytes: 4096 };
  const artifactResult = await artifacts.read(read, options);
  if (artifactResult.status !== "ok") throw new Error("Expected verified artifact bytes");
  const { bytes: readBytes, ...readMetadata } = artifactResult.output;
  check("artifacts.read", read, {
    ...artifactResult,
    output: { ...readMetadata, bytesBase64: codec.encodeBytes(readBytes) },
  });
  const memory = createFakeMemoryPort({
    workspaceId: "w",
    audience: "internal",
    scopes: ["agent"],
    sensitivities: ["private"],
    clock,
    maxBytes: 4096,
    maxItems: 1,
    maxMutations: 2,
  });
  const remember: PortInput<"memory.remember"> = {
    id: "note",
    expectedRevision: null,
    content: { text: "fact" },
    scope: "agent",
    audience: "internal",
    sensitivity: "private",
    expiresAt: null,
    provenance: [],
    idempotencyKey: "remember",
  };
  const item = check("memory.remember", remember, await memory.remember(remember, options));
  check("memory.read", { id: item.id }, await memory.read({ id: item.id }, options));
  const search: PortInput<"memory.search"> = {
    query: "fact",
    scope: "agent",
    limit: 1,
    maxBytes: 4096,
    asOf: new Date(0).toISOString(),
  };
  check("memory.search", search, await memory.search(search, options));
  const forget = { id: item.id, expectedRevision: item.revision, idempotencyKey: "forget" };
  check("memory.forget", forget, await memory.forget(forget, options));
  const children = createFakeCollaborationPort({
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
    maxBytes: 4096,
    maxRuns: 1,
  });
  const discovery = { capability: "analyze", limit: 1 };
  check("collaboration.discover", discovery, await children.discover(discovery, options));
  const invoke = { agentId: "child", version: "1.0.0", input: {}, idempotencyKey: "child" };
  const child = check("collaboration.invoke", invoke, await children.invoke(invoke, options));
  check(
    "collaboration.wait",
    { runIds: [child.runId] },
    await children.wait({ runIds: [child.runId] }, options),
  );
  check(
    "collaboration.result",
    { runId: child.runId },
    await children.result({ runId: child.runId }, options),
  );
  const sandbox = createFakeSandboxPort({
    scope,
    clock,
    commands: [
      {
        commandId: "analyze",
        argumentSchema: true,
        artifacts: [],
        run: async () => ({ exitCode: null, output: "" }),
      },
    ],
    inputArtifacts: [],
    credentialRefs: [],
    maxInstances: 2,
    maxMutations: 3,
    maxInputBytes: 4096,
    maxOutputBytes: 4096,
  });
  const execute = {
    commandId: "analyze",
    arguments: {},
    inputArtifacts: [],
    credentialRefs: [],
    maxOutputBytes: 64,
    idempotencyKey: "execute",
  };
  const execution = check("sandbox.execute", execute, await sandbox.execute(execute, options));
  const pause = { executionId: execution.executionId, idempotencyKey: "pause" };
  const checkpoint = check("sandbox.pause", pause, await sandbox.pause(pause, options));
  const resume = { checkpointId: checkpoint.checkpointId, idempotencyKey: "resume" };
  const restored = check("sandbox.resume", resume, await sandbox.resume(resume, options));
  expect(restored.executionId).not.toBe(execution.executionId);
  expect([...methods].sort()).toEqual(
    [
      "model.complete",
      "tools.invoke",
      "warehouse.catalog",
      "warehouse.describe",
      "warehouse.query",
      "artifacts.begin",
      "artifacts.write",
      "artifacts.commit",
      "artifacts.read",
      "memory.read",
      "memory.search",
      "memory.remember",
      "memory.forget",
      "collaboration.discover",
      "collaboration.invoke",
      "collaboration.wait",
      "collaboration.result",
      "sandbox.execute",
      "sandbox.pause",
      "sandbox.resume",
    ].sort(),
  );
  expect(clock.pendingTimers).toBe(0);
}, 20_000); // Compiles every port wire schema; ~3s alone, slower under parallel load.
