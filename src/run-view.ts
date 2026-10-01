/**
 * Run View - M12.3
 * One authorized, UI-shaped projection of a run: graph, approvals, artifacts,
 * evidence, cost and errors. Pure over already-scoped inputs; the caller loads
 * rows through the scope gate and this module never widens what they contain.
 */

import type { ArtifactMetadata } from "./artifact-storage.js";
import type { Evidence, VerificationStatus } from "./evidence-storage.js";
import type {
  GraphNode,
  ObservatoryError,
  ObservatoryProjection,
  UsageTotals,
} from "./observatory.js";
import { isTerminalRunStatus } from "./run-state.js";
import type { TerminalReceipt } from "./terminal-receipt-storage.js";

/** Bounds the payload; the full lists stay available on their own endpoints. */
export const MAX_VIEW_EVIDENCE = 200;
export const MAX_VIEW_ARTIFACTS = 100;

export type ApprovalState = "pending" | "approved" | "rejected" | "cancelled";

export interface RunView {
  run: ObservatoryProjection["run"] & { terminal: boolean; cancelRequested: boolean };
  graph: ObservatoryProjection["graph"];
  approvals: Array<{
    stepId: string;
    state: ApprovalState;
    requestedAt: string | null;
    decidedAt: string | null;
    waitedMs: number | null;
  }>;
  artifacts: Array<{
    id: string;
    kind: string;
    version: string;
    status: ArtifactMetadata["status"];
    sha256: string | null;
    bytes: number | null;
    /** Only a ready artifact whose hash is backed by verified evidence counts as verified. */
    verified: boolean;
    contentUrl: string | null;
  }>;
  evidence: {
    counts: Record<VerificationStatus, number>;
    items: Array<{
      id: string;
      kind: Evidence["kind"];
      verification: VerificationStatus;
      ref: string;
      createdAt: string;
    }>;
    truncated: boolean;
  };
  cost: {
    totals: UsageTotals;
    byModel: Record<string, UsageTotals>;
    byAgent: Record<string, UsageTotals>;
  };
  errors: ObservatoryError[];
  receipt: {
    status: TerminalReceipt["status"];
    sealedAt: string;
    evidenceCount: number;
    verifiedEvidenceCount: number;
    durationMs: number | null;
  } | null;
  /** What this viewer may do; the UI renders controls from this, never from status alone. */
  permissions: { canCancel: boolean; canDecideApproval: boolean };
  truncated: boolean;
}

export interface RunViewInput {
  projection: ObservatoryProjection;
  cancelRequested: boolean;
  evidence: Evidence[];
  artifacts: ArtifactMetadata[];
  receipt: TerminalReceipt | null;
  /** The caller's space; rows from any other workspace are dropped, not trusted. */
  spaceId: string;
  apiPrefix: string;
}

export function buildRunView(input: RunViewInput): RunView {
  const { projection, spaceId } = input;
  const evidence = input.evidence.filter((row) => row.workspaceId === spaceId);
  const artifacts = input.artifacts.filter((row) => row.workspaceId === spaceId);
  const terminal = isTerminalRunStatus(projection.run.status);

  const verifiedHashes = new Set(
    evidence
      .filter((row) => row.kind === "artifact_ref" && row.verification === "verified")
      .map(
        (row) =>
          `${(row as { artifactId: string }).artifactId}:${(row as { artifactSha256: string }).artifactSha256}`,
      ),
  );

  const counts: Record<VerificationStatus, number> = { verified: 0, unverified: 0, unavailable: 0 };
  for (const row of evidence) counts[row.verification] += 1;

  return {
    run: { ...projection.run, terminal, cancelRequested: input.cancelRequested },
    graph: projection.graph,
    approvals: projection.graph.nodes.filter((node) => node.kind === "approval").map(toApproval),
    artifacts: artifacts.slice(0, MAX_VIEW_ARTIFACTS).map((row) => ({
      id: row.id,
      kind: row.kind,
      version: row.version,
      status: row.status,
      sha256: row.sha256,
      bytes: row.bytes,
      verified:
        row.status === "ready" &&
        row.sha256 !== null &&
        verifiedHashes.has(`${row.id}:${row.sha256}`),
      contentUrl:
        row.status === "ready"
          ? `${input.apiPrefix}/artifacts/${encodeURIComponent(row.id)}/content`
          : null,
    })),
    evidence: {
      counts,
      items: evidence.slice(0, MAX_VIEW_EVIDENCE).map((row) => ({
        id: row.id,
        kind: row.kind,
        verification: row.verification,
        ref: evidenceRef(row),
        createdAt: row.createdAt.toISOString(),
      })),
      truncated: evidence.length > MAX_VIEW_EVIDENCE,
    },
    cost: {
      totals: projection.usage.totals,
      byModel: projection.usage.byModel,
      byAgent: projection.usage.byAgent,
    },
    errors: projection.errors,
    receipt:
      input.receipt && input.receipt.workspaceId === spaceId
        ? {
            status: input.receipt.status,
            sealedAt: input.receipt.sealedAt.toISOString(),
            evidenceCount: input.receipt.evidenceCount,
            verifiedEvidenceCount: input.receipt.verifiedEvidenceCount,
            durationMs: input.receipt.durationMs,
          }
        : null,
    permissions: {
      canCancel: !terminal && !input.cancelRequested,
      // No approval-decision route exists on this surface; approval is decided by the
      // host authority, so the viewer only sees state.
      canDecideApproval: false,
    },
    truncated: projection.truncated,
  };
}

function toApproval(node: GraphNode): RunView["approvals"][number] {
  const state: ApprovalState =
    node.status === "completed"
      ? "approved"
      : node.status === "failed"
        ? "rejected"
        : node.status === "cancelled"
          ? "cancelled"
          : "pending";
  return {
    stepId: node.id,
    state,
    requestedAt: node.startedAt,
    decidedAt: state === "pending" ? null : node.finishedAt,
    waitedMs: node.durationMs,
  };
}

/** A short, content-free reference: identifiers and hashes, never payloads. */
function evidenceRef(row: Evidence): string {
  switch (row.kind) {
    case "source":
      return `${row.sourceType}:${row.sourceLocation}@${row.sourceRevision}`;
    case "tool_call":
      return row.toolId;
    case "model_call":
      return row.modelId;
    case "artifact_ref":
      return row.artifactId;
    case "checkpoint":
      return `${row.checkpointId}#${row.checkpointRevision}`;
    default:
      return "";
  }
}
