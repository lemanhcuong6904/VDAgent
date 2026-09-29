/**
 * Production ArtifactPort. begin/write buffer bytes in memory for this run; commit checks the
 * declared length and SHA-256, then stores through the `artifacts.store` pool tool, which reads
 * the row back from PostgreSQL. Only a verified commit returns a `ready` reference.
 */
import { createHash } from "node:crypto";
import type { AgentContext } from "../agent-contract.js";
import type { AgentManifest, AgentPorts } from "../contracts/index.js";
import { MAX_ARTIFACT_BYTES } from "../tools/artifacts.js";
import {
  type CallOptions,
  failure,
  granted,
  hostScope,
  ID,
  inactive,
  poolScope,
} from "./host-outcome.js";

type Upload = {
  kind: string;
  version: string;
  mediaType: string;
  expectedBytes: number;
  expectedSha256: string;
  chunks: Buffer[];
  received: number;
  committed?: Awaited<ReturnType<AgentPorts["artifacts"]["commit"]>>;
  committing?: Promise<Awaited<ReturnType<AgentPorts["artifacts"]["commit"]>>>;
  commitOutcomeUnknown?: boolean;
};
type ArtifactCommitResult = Awaited<ReturnType<AgentPorts["artifacts"]["commit"]>>;
type BeginReplay = {
  fingerprint: string;
  result: Awaited<ReturnType<AgentPorts["artifacts"]["begin"]>>;
};
type CommitReplay = {
  uploadId: string;
  fingerprint: string;
  result: Promise<ArtifactCommitResult>;
};
const LIMITATION = `Uploads are buffered in the worker (max ${MAX_ARTIFACT_BYTES} bytes per artifact).`;

export function createHostArtifactPort(
  manifest: AgentManifest,
  context: AgentContext,
  correlationId: string,
): AgentPorts["artifacts"] {
  const declared = manifest.requiredPorts.includes("artifacts");
  const scope = hostScope(manifest, context);
  const uploads = new Map<string, Upload>();
  const beginsByKey = new Map<string, BeginReplay>();
  const commitsByKey = new Map<string, CommitReplay>();
  const gate = (tool: string, options: CallOptions) => {
    if (!declared) return failure("denied", "port_not_declared", correlationId);
    if (!granted(manifest, context, tool))
      return failure("denied", "artifact_not_granted", correlationId);
    if (inactive(options)) return failure("failed", "inactive_call", correlationId);
    return undefined;
  };
  const ok = <T>(output: T) => ({
    status: "ok" as const,
    output,
    evidence: [],
    limitations: [LIMITATION],
  });

  return {
    async begin(input, options) {
      const denied = gate("artifacts.store", options);
      if (denied) return denied;
      if (!ID.test(input.idempotencyKey))
        return failure("denied", "invalid_idempotency_key", correlationId);
      if (input.expectedBytes > MAX_ARTIFACT_BYTES)
        return failure("denied", "artifact_too_large", correlationId);
      const fingerprint = JSON.stringify([
        input.kind,
        input.version,
        input.mediaType,
        input.expectedBytes,
        input.expectedSha256.toLowerCase(),
      ]);
      const previous = beginsByKey.get(input.idempotencyKey);
      if (previous) {
        if (previous.fingerprint !== fingerprint)
          return failure("denied", "idempotency_conflict", correlationId);
        return previous.result;
      }
      const uploadId = `${scope.runId}.upload.${uploads.size + 1}`;
      if (!uploads.has(uploadId)) {
        uploads.set(uploadId, { ...input, chunks: [], received: 0 });
      }
      const result = ok({
        uploadId,
        artifact: {
          id: uploadId,
          workspaceId: scope.workspaceId,
          ownerRunId: scope.runId,
          kind: input.kind,
          version: input.version,
          status: "pending" as const,
        },
      });
      beginsByKey.set(input.idempotencyKey, { fingerprint, result });
      return result;
    },
    async write(input, options) {
      const denied = gate("artifacts.store", options);
      if (denied) return denied;
      const upload = uploads.get(input.uploadId);
      if (!upload || upload.committed) return failure("failed", "unknown_upload", correlationId);
      // Replayed chunk at the same offset is accepted once; a gap or overlap is rejected.
      if (input.offset + input.bytes.byteLength <= upload.received)
        return ok({ acceptedBytes: upload.received });
      if (input.offset !== upload.received)
        return failure("failed", "offset_mismatch", correlationId);
      if (upload.received + input.bytes.byteLength > upload.expectedBytes)
        return failure("failed", "artifact_length_mismatch", correlationId);
      upload.chunks.push(Buffer.from(input.bytes));
      upload.received += input.bytes.byteLength;
      return ok({ acceptedBytes: upload.received });
    },
    async commit(input, options) {
      const denied = gate("artifacts.store", options);
      if (denied) return denied;
      if (!ID.test(input.idempotencyKey))
        return failure("denied", "invalid_idempotency_key", correlationId);
      const upload = uploads.get(input.uploadId);
      if (!upload) return failure("failed", "unknown_upload", correlationId);
      const fingerprint = JSON.stringify([
        input.uploadId,
        upload.kind,
        upload.version,
        upload.mediaType,
        upload.expectedBytes,
        upload.expectedSha256.toLowerCase(),
      ]);
      const previous = commitsByKey.get(input.idempotencyKey);
      if (previous) {
        if (previous.uploadId !== input.uploadId || previous.fingerprint !== fingerprint)
          return failure("denied", "idempotency_conflict", correlationId);
        return previous.result;
      }
      if (upload.committed) {
        const replay = Promise.resolve(upload.committed);
        commitsByKey.set(input.idempotencyKey, {
          uploadId: input.uploadId,
          fingerprint,
          result: replay,
        });
        return replay;
      }
      if (upload.commitOutcomeUnknown) {
        const outcome = failure("unknown", "artifact_outcome_unknown", correlationId);
        commitsByKey.set(input.idempotencyKey, {
          uploadId: input.uploadId,
          fingerprint,
          result: Promise.resolve(outcome),
        });
        return outcome;
      }
      if (upload.committing) {
        commitsByKey.set(input.idempotencyKey, {
          uploadId: input.uploadId,
          fingerprint,
          result: upload.committing,
        });
        return upload.committing;
      }
      const content = Buffer.concat(upload.chunks);
      const sha256 = createHash("sha256").update(content).digest("hex");
      if (content.byteLength !== upload.expectedBytes) {
        const result = failure("failed", "artifact_length_mismatch", correlationId);
        commitsByKey.set(input.idempotencyKey, {
          uploadId: input.uploadId,
          fingerprint,
          result: Promise.resolve(result),
        });
        return result;
      }
      if (sha256 !== upload.expectedSha256.toLowerCase()) {
        const result = failure("failed", "artifact_hash_mismatch", correlationId);
        commitsByKey.set(input.idempotencyKey, {
          uploadId: input.uploadId,
          fingerprint,
          result: Promise.resolve(result),
        });
        return result;
      }
      const committing = (async (): Promise<ArtifactCommitResult> => {
        let stored: { id: string; sha256: string; bytes: number };
        try {
          stored = (await context.pool.call(
            "artifacts.store",
            {
              kind: upload.kind,
              version: upload.version,
              mediaType: upload.mediaType,
              bytesBase64: content.toString("base64"),
            },
            poolScope(manifest, context, options.signal, input.idempotencyKey),
            manifest.id,
          )) as typeof stored;
        } catch {
          // The row may exist even though the call failed. Cache the unknown
          // result and refuse new commit keys to avoid creating a duplicate.
          upload.commitOutcomeUnknown = true;
          return failure("unknown", "artifact_outcome_unknown", correlationId);
        }
        if (stored.sha256 !== sha256 || stored.bytes !== content.byteLength) {
          upload.commitOutcomeUnknown = true;
          return failure("unknown", "artifact_readback_mismatch", correlationId);
        }
        upload.committed = ok({
          id: stored.id,
          workspaceId: scope.workspaceId,
          ownerRunId: scope.runId,
          kind: upload.kind,
          version: upload.version,
          status: "ready" as const,
          sha256,
          bytes: content.byteLength,
        });
        upload.chunks = [];
        return upload.committed;
      })().catch(() => {
        upload.commitOutcomeUnknown = true;
        return failure("unknown", "artifact_outcome_unknown", correlationId);
      });
      upload.committing = committing;
      commitsByKey.set(input.idempotencyKey, {
        uploadId: input.uploadId,
        fingerprint,
        result: committing,
      });
      void committing.finally(() => {
        if (upload.committing === committing) upload.committing = undefined;
      });
      return committing;
    },
    async read(input, options) {
      const denied = gate("artifacts.read", options);
      if (denied) return denied;
      let result: {
        found: boolean;
        artifact?: {
          id: string;
          workspaceId: string;
          ownerRunId: string;
          kind: string;
          version: string;
          status: "ready";
          sha256: string;
          bytes: number;
        };
        bytesBase64?: string;
      };
      try {
        result = (await context.pool.call(
          "artifacts.read",
          { artifactId: input.artifactId },
          poolScope(manifest, context, options.signal),
          manifest.id,
        )) as typeof result;
      } catch {
        return failure("failed", "artifact_read_failed", correlationId);
      }
      if (!result.found || !result.artifact || result.bytesBase64 === undefined)
        return failure("failed", "artifact_not_found", correlationId);
      const all = Buffer.from(result.bytesBase64, "base64");
      const bytes = all.subarray(input.offset, input.offset + input.maxBytes);
      const end = input.offset + bytes.byteLength;
      return ok({
        artifact: result.artifact,
        bytes: new Uint8Array(bytes),
        nextOffset: end < all.byteLength ? end : null,
      });
    },
  };
}
