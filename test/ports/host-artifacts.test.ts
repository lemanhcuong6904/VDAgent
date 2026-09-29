import { createHash } from "node:crypto";
import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import type { AgentContext } from "../../src/agent-contract.js";
import type { AgentManifest } from "../../src/contracts/index.js";
import { createHostArtifactPort } from "../../src/ports/host-artifacts.js";
import { McpToolPool } from "../../src/tool-pool.js";

const manifest: AgentManifest = {
  apiVersion: "agent.v1",
  id: "artifact-agent",
  version: "1.0.0",
  displayName: "Artifact agent",
  inputSchema: true,
  outputSchema: true,
  capabilities: [],
  requiredPorts: ["artifacts"],
  toolGrants: [{ toolId: "artifacts.store", version: "1", effect: "write" }],
  limits: {
    timeoutMs: 30_000,
    maxInputBytes: 4096,
    maxOutputBytes: 4096,
    maxEventBytes: 4096,
    maxCheckpointBytes: 4096,
    maxModelCalls: 0,
    maxToolCalls: 10,
    maxChildRuns: 0,
    maxDepth: 1,
    maxCostUsd: 1,
  },
  compatibility: { minHostVersion: "1.0.0" },
};

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function artifactPort(store: (content: Buffer) => Promise<unknown>) {
  const pool = new McpToolPool();
  pool.register({
    name: "artifacts.store",
    description: "Store artifact",
    schema: Type.Object({
      kind: Type.String(),
      version: Type.String(),
      mediaType: Type.String(),
      bytesBase64: Type.String(),
    }),
    mutates: true,
    agents: [manifest.id],
    authorize: () => true,
    async execute(input) {
      const value = input as { bytesBase64: string };
      return store(Buffer.from(value.bytesBase64, "base64"));
    },
  });
  const context = {
    runId: "run-artifacts",
    sessionId: "session-1",
    userId: "user-1",
    spaceId: "space-1",
    signal: new AbortController().signal,
    tools: pool.forAgent(manifest.id),
    pool,
    runtime: { prompt: async () => "" },
  } as unknown as AgentContext;
  return createHostArtifactPort(manifest, context, "correlation-1");
}

function options() {
  return { signal: new AbortController().signal, deadline: Date.now() + 10_000 };
}

describe("host artifact idempotency", () => {
  it("rejects a begin key reused with different artifact metadata", async () => {
    const port = artifactPort(async () => ({ id: "stored", sha256: "", bytes: 0 }));
    const begin = {
      kind: "report",
      version: "1",
      mediaType: "text/plain",
      expectedBytes: 3,
      expectedSha256: createHash("sha256").update("abc").digest("hex"),
      idempotencyKey: "begin-key",
    };
    const first = await port.begin(begin, options());
    const replay = await port.begin({ ...begin }, options());
    const conflict = await port.begin({ ...begin, kind: "image" }, options());

    expect(first).toMatchObject({ status: "ok", output: { uploadId: expect.any(String) } });
    expect(replay).toEqual(first);
    expect(conflict).toMatchObject({ status: "denied", error: { code: "idempotency_conflict" } });
  });

  it("coalesces concurrent commit calls, including different keys for one upload", async () => {
    const started = deferred();
    const finishStore = deferred();
    let storeCalls = 0;
    const content = Buffer.from("verified bytes");
    const sha256 = createHash("sha256").update(content).digest("hex");
    const port = artifactPort(async (bytes) => {
      storeCalls++;
      started.resolve();
      await finishStore.promise;
      return {
        id: "artifact-1",
        sha256: createHash("sha256").update(bytes).digest("hex"),
        bytes: bytes.byteLength,
      };
    });
    const startedUpload = await port.begin(
      {
        kind: "report",
        version: "1",
        mediaType: "text/plain",
        expectedBytes: content.byteLength,
        expectedSha256: sha256,
        idempotencyKey: "begin-concurrent",
      },
      options(),
    );
    if (startedUpload.status !== "ok") throw new Error("begin failed");
    await port.write(
      {
        uploadId: startedUpload.output.uploadId,
        offset: 0,
        bytes: new Uint8Array(content),
        idempotencyKey: "write-concurrent",
      },
      options(),
    );

    const first = port.commit(
      { uploadId: startedUpload.output.uploadId, idempotencyKey: "commit-one" },
      options(),
    );
    await started.promise;
    const sameKey = port.commit(
      { uploadId: startedUpload.output.uploadId, idempotencyKey: "commit-one" },
      options(),
    );
    const differentKey = port.commit(
      { uploadId: startedUpload.output.uploadId, idempotencyKey: "commit-two" },
      options(),
    );
    finishStore.resolve();
    const [firstResult, sameKeyResult, differentKeyResult] = await Promise.all([
      first,
      sameKey,
      differentKey,
    ]);

    expect(storeCalls).toBe(1);
    expect(sameKeyResult).toEqual(firstResult);
    expect(differentKeyResult).toEqual(firstResult);
    expect(firstResult).toMatchObject({
      status: "ok",
      output: { id: "artifact-1", status: "ready" },
    });
  });

  it("keeps an uncertain commit outcome from retrying a possible durable write", async () => {
    const content = Buffer.from("maybe committed");
    const sha256 = createHash("sha256").update(content).digest("hex");
    let storeCalls = 0;
    const port = artifactPort(async () => {
      storeCalls++;
      throw new Error("connection lost after database commit");
    });
    const started = await port.begin(
      {
        kind: "report",
        version: "1",
        mediaType: "text/plain",
        expectedBytes: content.byteLength,
        expectedSha256: sha256,
        idempotencyKey: "begin-unknown",
      },
      options(),
    );
    if (started.status !== "ok") throw new Error("begin failed");
    await port.write(
      {
        uploadId: started.output.uploadId,
        offset: 0,
        bytes: new Uint8Array(content),
        idempotencyKey: "write-unknown",
      },
      options(),
    );

    const first = await port.commit(
      { uploadId: started.output.uploadId, idempotencyKey: "commit-unknown" },
      options(),
    );
    const replay = await port.commit(
      { uploadId: started.output.uploadId, idempotencyKey: "commit-unknown" },
      options(),
    );
    const newKey = await port.commit(
      { uploadId: started.output.uploadId, idempotencyKey: "commit-retry" },
      options(),
    );

    expect(first).toMatchObject({ status: "unknown", error: { code: "artifact_outcome_unknown" } });
    expect(replay).toEqual(first);
    expect(newKey).toMatchObject({
      status: "unknown",
      error: { code: "artifact_outcome_unknown" },
    });
    expect(storeCalls).toBe(1);
  });
});
