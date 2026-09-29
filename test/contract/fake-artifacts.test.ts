import { createHash } from "node:crypto";
import { expect, it } from "vitest";
import type { ArtifactPort, PortOutcome } from "../../src/contracts/ports.js";
import { createFakeArtifactPort } from "../../src/testkit/artifacts.js";
import { ManualClock } from "../../src/testkit/call.js";

const options = { signal: new AbortController().signal, deadline: 1000 };
const bytes = new TextEncoder().encode("héllo 🌎");
const request = {
  kind: "text",
  version: "1",
  mediaType: "text/plain",
  expectedBytes: bytes.length,
  expectedSha256: createHash("sha256").update(bytes).digest("hex"),
  idempotencyKey: "begin",
};
function setup(overrides: Partial<Parameters<typeof createFakeArtifactPort>[0]> = {}) {
  return createFakeArtifactPort({
    workspaceId: "w",
    ownerRunId: "r",
    clock: new ManualClock(),
    maxArtifactBytes: 1024,
    maxTotalBytes: 2048,
    maxUploads: 2,
    maxMutations: 20,
    maxRequestBytes: 4096,
    maxResponseBytes: 4096,
    ...overrides,
  });
}
function output<T>(result: PortOutcome<T>): T {
  expect(result.status).toBe("ok");
  if (result.status !== "ok") throw new Error("Expected success");
  return result.output;
}
async function publish(port: ArtifactPort) {
  const begin = output(await port.begin(request, options));
  await port.write(
    { uploadId: begin.uploadId, bytes, offset: 0, idempotencyKey: "write" },
    options,
  );
  return output(await port.commit({ uploadId: begin.uploadId, idempotencyKey: "commit" }, options));
}
it("publishes only after byte verification and reads bounded cross-chunk ranges", async () => {
  const port = setup();
  const begin = output(await port.begin(request, options));
  expect(begin.artifact).toMatchObject({ status: "pending", workspaceId: "w", ownerRunId: "r" });
  expect(
    await port.read({ artifactId: begin.artifact.id, offset: 0, maxBytes: 10 }, options),
  ).toMatchObject({ status: "unknown" });
  await port.write(
    { uploadId: begin.uploadId, offset: 0, bytes: bytes.slice(0, 3), idempotencyKey: "chunk1" },
    options,
  );
  await port.write(
    { uploadId: begin.uploadId, offset: 3, bytes: bytes.slice(3), idempotencyKey: "chunk2" },
    options,
  );
  const ready = output(
    await port.commit({ uploadId: begin.uploadId, idempotencyKey: "commit" }, options),
  );
  expect(ready).toMatchObject({
    status: "ready",
    bytes: bytes.length,
    sha256: request.expectedSha256,
  });
  const read = output(await port.read({ artifactId: ready.id, offset: 1, maxBytes: 5 }, options));
  expect(read.bytes).toEqual(bytes.slice(1, 6));
  expect(read.nextOffset).toBe(6);
  read.bytes.fill(0);
  read.artifact.sha256 = "tampered";
  const again = output(
    await port.read({ artifactId: ready.id, offset: 0, maxBytes: 1024 }, options),
  );
  expect(again.bytes).toEqual(bytes);
  expect(again.artifact.sha256).toBe(request.expectedSha256);
  expect(again.nextOffset).toBeNull();
});
it("deduplicates begin/write/commit and rejects changed keys, offsets and ready writes", async () => {
  const port = setup();
  const begin = await port.begin(request, options);
  expect(await port.begin(request, options)).toEqual(begin);
  const uploadId = output(begin).uploadId;
  const write = { uploadId, offset: 0, bytes: bytes.slice(), idempotencyKey: "write" };
  const saved = await port.write(write, options);
  expect(await port.write(write, options)).toEqual(saved);
  expect(await port.write({ ...write, bytes: new Uint8Array([1]) }, options)).toMatchObject({
    status: "denied",
    error: { code: "idempotency_conflict" },
  });
  expect(await port.write({ ...write, idempotencyKey: "overlap" }, options)).toMatchObject({
    status: "denied",
    error: { code: "offset_conflict" },
  });
  const commit = { uploadId, idempotencyKey: "commit" };
  const ready = await port.commit(commit, options);
  expect(await port.commit(commit, options)).toEqual(ready);
  expect(
    await port.write({ ...write, offset: bytes.length, idempotencyKey: "late" }, options),
  ).toMatchObject({ status: "denied", error: { code: "upload_closed" } });
});
it("keeps short uploads pending and hash mismatches unknown without returning empty success", async () => {
  const port = setup();
  const { uploadId } = output(await port.begin(request, options));
  expect(await port.commit({ uploadId, idempotencyKey: "early" }, options)).toMatchObject({
    status: "denied",
    error: { code: "upload_incomplete" },
  });
  const wrong = bytes.slice();
  wrong[0] ^= 1;
  await port.write({ uploadId, offset: 0, bytes: wrong, idempotencyKey: "wrong" }, options);
  expect(await port.commit({ uploadId, idempotencyKey: "commit" }, options)).toMatchObject({
    status: "unknown",
    error: { code: "artifact_hash_mismatch" },
  });
  expect(await port.commit({ uploadId, idempotencyKey: "retry" }, options)).toMatchObject({
    status: "unknown",
  });
  expect(await port.read({ artifactId: uploadId, offset: 0, maxBytes: 1 }, options)).toMatchObject({
    status: "unknown",
  });
  expect(await port.read({ artifactId: "missing", offset: 0, maxBytes: 1 }, options)).toMatchObject(
    { status: "unknown" },
  );
});
it("supports verified empty artifacts and EOF, while rejecting out-of-range offsets", async () => {
  const port = setup();
  const empty = {
    ...request,
    expectedBytes: 0,
    expectedSha256: createHash("sha256").digest("hex"),
  };
  const { uploadId } = output(await port.begin(empty, options));
  await port.commit({ uploadId, idempotencyKey: "commit" }, options);
  expect(
    output(await port.read({ artifactId: uploadId, offset: 0, maxBytes: 1 }, options)),
  ).toMatchObject({ bytes: new Uint8Array(), nextOffset: null });
  expect(await port.read({ artifactId: uploadId, offset: 1, maxBytes: 1 }, options)).toMatchObject({
    status: "denied",
  });
});
it("denies scope expansion, malformed requests and unowned uploads", async () => {
  const port = setup();
  const artifact = await publish(port);
  const other = setup();
  expect(
    await other.read({ artifactId: artifact.id, offset: 0, maxBytes: 1 }, options),
  ).toMatchObject({ status: "unknown" });
  for (const extra of [
    { workspaceId: "other" },
    { expectedBytes: -1 },
    { expectedSha256: "fake" },
    { mediaType: "text/plain\r\nX:evil" },
  ])
    expect(await port.begin({ ...request, ...extra }, options)).toMatchObject({ status: "denied" });
  let accessed = false;
  const bad = {
    uploadId: artifact.id,
    offset: 0,
    idempotencyKey: "accessor",
    get bytes() {
      accessed = true;
      return bytes;
    },
  };
  expect(await port.write(bad, options)).toMatchObject({ status: "denied" });
  expect(accessed).toBe(false);
  expect(
    await other.commit({ uploadId: artifact.id, idempotencyKey: "commit" }, options),
  ).toMatchObject({ status: "denied" });
});
it("bounds reservations, chunks, response size and idempotency ledger", async () => {
  const port = setup({ maxTotalBytes: bytes.length, maxMutations: 3 });
  const { uploadId } = output(await port.begin(request, options));
  expect(await port.begin({ ...request, idempotencyKey: "second" }, options)).toMatchObject({
    status: "denied",
    error: { code: "storage_limit" },
  });
  expect(
    await port.write(
      { uploadId, offset: 0, bytes: new Uint8Array(bytes.length + 1), idempotencyKey: "large" },
      options,
    ),
  ).toMatchObject({ status: "denied", error: { code: "chunk_limit" } });
  expect(await port.commit({ uploadId, idempotencyKey: "commit" }, options)).toMatchObject({
    status: "denied",
    error: { code: "mutation_limit" },
  });
  expect(await setup({ maxArtifactBytes: 1 }).begin(request, options)).toMatchObject({
    status: "denied",
  });
  const bounded = setup({ maxArtifactBytes: 2000, maxResponseBytes: 512 });
  const content = new Uint8Array(1000);
  const started = output(
    await bounded.begin(
      {
        ...request,
        expectedBytes: 1000,
        expectedSha256: createHash("sha256").update(content).digest("hex"),
      },
      options,
    ),
  );
  await bounded.write(
    { uploadId: started.uploadId, offset: 0, bytes: content, idempotencyKey: "write" },
    options,
  );
  await bounded.commit({ uploadId: started.uploadId, idempotencyKey: "commit" }, options);
  expect(
    await bounded.read({ artifactId: started.uploadId, offset: 0, maxBytes: 1000 }, options),
  ).toMatchObject({ status: "failed", error: { code: "output_limit" } });
});
it("snapshots bytes before asynchronous work and preserves unknown timeout replay", async () => {
  const clock = new ManualClock();
  let release!: () => void;
  let calls = 0;
  const port = setup({
    clock,
    before: async (operation) => {
      if (operation !== "write") return;
      calls++;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    },
  });
  const { uploadId } = output(await port.begin(request, options));
  const original = bytes.slice();
  const pending = port.write(
    { uploadId, offset: 0, bytes: original, idempotencyKey: "write" },
    options,
  );
  original.fill(0);
  release();
  expect(output(await pending)).toEqual({ acceptedBytes: bytes.length });
  expect(output(await port.commit({ uploadId, idempotencyKey: "commit" }, options))).toMatchObject({
    sha256: request.expectedSha256,
  });
  const second = output(await port.begin({ ...request, idempotencyKey: "second" }, options));
  const write = { uploadId: second.uploadId, offset: 0, bytes, idempotencyKey: "timeout" };
  const timed = port.write(write, { ...options, deadline: 10 });
  clock.advance(10);
  expect(await timed).toMatchObject({ status: "unknown" });
  release();
  expect(await port.write(write, options)).toMatchObject({ status: "unknown" });
  expect(calls).toBe(2);
  expect(
    await port.commit({ uploadId: second.uploadId, idempotencyKey: "incomplete" }, options),
  ).toMatchObject({ status: "denied", error: { code: "upload_incomplete" } });
  expect(clock.pendingTimers).toBe(0);
});
it("does not dispatch cancelled uploads and redacts injected faults", async () => {
  let calls = 0;
  const port = setup({
    before: async () => {
      calls++;
      throw new Error("private provider credential");
    },
  });
  const controller = new AbortController();
  controller.abort();
  expect(await port.begin(request, { ...options, signal: controller.signal })).toMatchObject({
    status: "denied",
  });
  expect(await port.begin(request, { ...options, deadline: 0 })).toMatchObject({
    status: "denied",
  });
  expect(calls).toBe(0);
  const failure = await port.begin(request, options);
  expect(failure).toMatchObject({ status: "unknown", error: { safeMessage: "operation_failed" } });
  expect(JSON.stringify(failure)).not.toContain("credential");
});
