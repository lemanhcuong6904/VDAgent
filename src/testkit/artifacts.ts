import { createHash } from "node:crypto";
import type { ArtifactRef } from "../contracts/generated/artifact-ref.js";
import type { ArtifactPort, CallOptions, PortOutcome } from "../contracts/ports.js";
import { runFakeCall, type TestClock } from "./call.js";
import { encodeBoundedJson } from "./json.js";

type Operation = "begin" | "write" | "commit" | "read";
type Ready = Extract<ArtifactRef, { status: "ready" }>;
type Upload = {
  artifact: ArtifactRef;
  expectedBytes: number;
  expectedSha256: string;
  chunks: Uint8Array[];
  written: number;
};
const validId = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const digest = (bytes: Uint8Array | string) => createHash("sha256").update(bytes).digest("hex");

/** Host-owned, isolated in-memory uploads; ready is derived from stored bytes, never a claim. */
export function createFakeArtifactPort(config: {
  workspaceId: string;
  ownerRunId: string;
  clock: TestClock;
  maxArtifactBytes: number;
  maxTotalBytes: number;
  maxUploads: number;
  maxMutations: number;
  maxRequestBytes: number;
  maxResponseBytes: number;
  before?: (operation: Operation, signal: AbortSignal) => Promise<void>;
}): ArtifactPort {
  const {
    workspaceId,
    ownerRunId,
    clock,
    maxArtifactBytes,
    maxTotalBytes,
    maxUploads,
    maxMutations,
    maxRequestBytes,
    maxResponseBytes,
    before,
  } = config;
  for (const limit of [
    maxArtifactBytes,
    maxTotalBytes,
    maxUploads,
    maxMutations,
    maxRequestBytes,
    maxResponseBytes,
  ])
    if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("Invalid artifact limits");
  if (!validId(workspaceId) || !validId(ownerRunId)) throw new Error("Invalid artifact scope");
  const uploads = new Map<string, Upload>();
  const ledger = new Map<string, { fingerprint: string; result: Promise<PortOutcome<unknown>> }>();
  let reservedBytes = 0;
  const denied = <T>(code: string, unknown = false): PortOutcome<T> => {
    const error = {
      code,
      retryable: false as const,
      safeMessage: code,
      correlationId: "fake-artifact",
    };
    return unknown
      ? { status: "unknown", error: { ...error, class: "unknown" }, evidence: [] }
      : { status: "denied", error: { ...error, class: "policy" }, evidence: [] };
  };
  const ok = <T>(output: T): PortOutcome<T> => ({
    status: "ok",
    output,
    evidence: [],
    limitations: ["Synthetic artifact storage; no durable receipt"],
  });
  function parse<T>(input: T, fields: string[]): T | null {
    try {
      const value = JSON.parse(encodeBoundedJson(input, maxRequestBytes));
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
  async function call<T>(
    operation: Operation,
    options: CallOptions,
    effect: () => PortOutcome<T>,
  ): Promise<PortOutcome<T>> {
    const result = await runFakeCall(
      async (signal) => {
        if (before) await before(operation, signal);
        if (signal.aborted) throw new Error("inactive_call");
        return effect();
      },
      options,
      {
        maxOutputBytes: maxResponseBytes,
        correlationId: "fake-artifact",
        effect: operation === "read" ? "read" : "write",
      },
      clock,
    );
    return result.status === "ok" ? result.output : result;
  }
  async function mutate<T>(
    operation: Operation,
    input: { idempotencyKey: string },
    options: CallOptions,
    effect: () => PortOutcome<T>,
  ): Promise<PortOutcome<T>> {
    if (!validId(input.idempotencyKey)) return denied("invalid_idempotency_key");
    if (
      options.signal.aborted ||
      !Number.isFinite(options.deadline) ||
      options.deadline <= clock.now()
    )
      return denied("inactive_call");
    const fingerprint = digest(JSON.stringify([operation, canonical(input)]));
    const previous = ledger.get(input.idempotencyKey);
    if (previous) {
      if (previous.fingerprint !== fingerprint) return denied("idempotency_conflict");
      const replay = await runFakeCall(
        () => previous.result as Promise<PortOutcome<T>>,
        options,
        { maxOutputBytes: maxResponseBytes, correlationId: "fake-artifact", effect: "write" },
        clock,
      );
      return replay.status === "ok" ? replay.output : replay;
    }
    if (ledger.size >= maxMutations) return denied("mutation_limit");
    let resolve!: (result: PortOutcome<T>) => void;
    const result = new Promise<PortOutcome<T>>((done) => {
      resolve = done;
    });
    ledger.set(input.idempotencyKey, { fingerprint, result });
    void call(operation, options, effect).then(resolve);
    return structuredClone(await result);
  }
  return {
    begin(input, options) {
      const value = parse(input, [
        "kind",
        "version",
        "mediaType",
        "expectedBytes",
        "expectedSha256",
        "idempotencyKey",
      ]);
      if (
        !value ||
        !validId(value.kind) ||
        !validId(value.version) ||
        typeof value.mediaType !== "string" ||
        !/^[a-zA-Z0-9!#$&^_.+-]+\/[a-zA-Z0-9!#$&^_.+-]+$/.test(value.mediaType) ||
        value.mediaType.length > 128 ||
        !Number.isSafeInteger(value.expectedBytes) ||
        value.expectedBytes < 0 ||
        value.expectedBytes > maxArtifactBytes ||
        typeof value.expectedSha256 !== "string" ||
        !/^[a-f0-9]{64}$/.test(value.expectedSha256)
      )
        return Promise.resolve(denied("invalid_upload"));
      return mutate("begin", value, options, () => {
        if (uploads.size >= maxUploads || value.expectedBytes > maxTotalBytes - reservedBytes)
          return denied("storage_limit");
        const uploadId = `fake-upload-${uploads.size + 1}`;
        const artifact: Extract<ArtifactRef, { status: "pending" }> = {
          id: uploadId,
          workspaceId,
          ownerRunId,
          kind: value.kind,
          version: value.version,
          status: "pending",
        };
        const result = ok({ uploadId, artifact });
        encodeBoundedJson(result, maxResponseBytes);
        uploads.set(uploadId, {
          artifact,
          expectedBytes: value.expectedBytes,
          expectedSha256: value.expectedSha256,
          chunks: [],
          written: 0,
        });
        reservedBytes += value.expectedBytes;
        return result;
      });
    },
    write(input, options) {
      let value: {
        uploadId: string;
        offset: number;
        base64: string;
        idempotencyKey: string;
      } | null;
      try {
        // Inspect metadata before touching bytes so getters/unknown authority never execute.
        const fields = Object.getOwnPropertyDescriptors(input);
        if (
          Object.getOwnPropertySymbols(input).length ||
          Object.keys(fields).length !== 4 ||
          ["uploadId", "offset", "bytes", "idempotencyKey"].some(
            (field) => !fields[field]?.enumerable || !("value" in fields[field]),
          ) ||
          typeof fields.uploadId.value !== "string" ||
          typeof fields.offset.value !== "number" ||
          typeof fields.idempotencyKey.value !== "string" ||
          !(fields.bytes.value instanceof Uint8Array) ||
          fields.bytes.value.byteLength > maxArtifactBytes
        )
          return Promise.resolve(denied("invalid_chunk"));
        value = parse(
          {
            uploadId: fields.uploadId.value,
            offset: fields.offset.value,
            base64: Buffer.from(fields.bytes.value).toString("base64"),
            idempotencyKey: fields.idempotencyKey.value,
          },
          ["uploadId", "offset", "base64", "idempotencyKey"],
        );
      } catch {
        return Promise.resolve(denied("invalid_chunk"));
      }
      if (
        !value ||
        !validId(value.uploadId) ||
        !Number.isSafeInteger(value.offset) ||
        value.offset < 0
      )
        return Promise.resolve(denied("invalid_chunk"));
      const snapshot = value;
      return mutate("write", snapshot, options, () => {
        const upload = uploads.get(snapshot.uploadId);
        if (!upload) return denied("upload_unavailable");
        if (upload.artifact.status !== "pending") return denied("upload_closed");
        if (snapshot.offset !== upload.written) return denied("offset_conflict");
        const bytes = Buffer.from(snapshot.base64, "base64");
        if (bytes.length === 0 || bytes.length > upload.expectedBytes - upload.written)
          return denied("chunk_limit");
        const result = ok({ acceptedBytes: bytes.length });
        encodeBoundedJson(result, maxResponseBytes);
        upload.chunks.push(bytes);
        upload.written += bytes.length;
        return result;
      });
    },
    commit(input, options) {
      const value = parse(input, ["uploadId", "idempotencyKey"]);
      if (!value || !validId(value.uploadId)) return Promise.resolve(denied("invalid_commit"));
      return mutate("commit", value, options, () => {
        const upload = uploads.get(value.uploadId);
        if (!upload) return denied("upload_unavailable");
        if (upload.artifact.status === "unknown") return denied("artifact_integrity_unknown", true);
        if (upload.artifact.status === "ready") return ok(upload.artifact);
        if (upload.written !== upload.expectedBytes) return denied("upload_incomplete");
        const hash = createHash("sha256");
        for (const chunk of upload.chunks) hash.update(chunk);
        const sha256 = hash.digest("hex");
        if (sha256 !== upload.expectedSha256) {
          upload.artifact = { ...upload.artifact, status: "unknown" };
          return denied("artifact_hash_mismatch", true);
        }
        const artifact: Ready = {
          ...upload.artifact,
          status: "ready",
          sha256,
          bytes: upload.written,
        };
        const result = ok(artifact);
        encodeBoundedJson(result, maxResponseBytes);
        upload.artifact = artifact;
        return result;
      });
    },
    async read(input, options) {
      const value = parse(input, ["artifactId", "offset", "maxBytes"]);
      if (
        !value ||
        !validId(value.artifactId) ||
        !Number.isSafeInteger(value.offset) ||
        value.offset < 0 ||
        !Number.isSafeInteger(value.maxBytes) ||
        value.maxBytes < 1 ||
        value.maxBytes > maxArtifactBytes
      )
        return denied("invalid_read");
      const result = await call<{ artifact: Ready; base64: string; nextOffset: number | null }>(
        "read",
        options,
        () => {
          const upload = uploads.get(value.artifactId);
          if (upload?.artifact.status !== "ready")
            return denied<{ artifact: Ready; base64: string; nextOffset: number | null }>(
              "artifact_unavailable",
              true,
            );
          if (value.offset > upload.written) return denied("invalid_offset");
          const end = Math.min(upload.written, value.offset + value.maxBytes);
          const bytes = Buffer.alloc(end - value.offset);
          let start = 0;
          for (const chunk of upload.chunks) {
            const from = Math.max(start, value.offset);
            const to = Math.min(start + chunk.byteLength, end);
            if (to > from) bytes.set(chunk.subarray(from - start, to - start), from - value.offset);
            start += chunk.byteLength;
            if (start >= end) break;
          }
          return ok({
            artifact: upload.artifact,
            base64: bytes.toString("base64"),
            nextOffset: end < upload.written ? end : null,
          });
        },
      );
      if (result.status !== "ok") return result;
      return {
        ...result,
        output: {
          artifact: result.output.artifact,
          bytes: new Uint8Array(Buffer.from(result.output.base64, "base64")),
          nextOffset: result.output.nextOffset,
        },
      };
    },
  };
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
