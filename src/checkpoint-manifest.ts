/**
 * Checkpoint Manifest
 * M9.6: Checkpoint lineage tracking with parent/base/source/hash
 *
 * A checkpoint captures agent state at a point in time. The manifest tracks
 * lineage so the platform can restore, diff, and safely prune old checkpoints.
 */

import { createHash } from "node:crypto";

/** Checkpoint identity: unique within a run */
export interface CheckpointId {
  /** Run the checkpoint belongs to */
  runId: string;
  /** Monotonic sequence within the run (0 = initial state before any work) */
  sequence: number;
}

/** Lineage: how this checkpoint relates to others */
export interface CheckpointLineage {
  /** Direct predecessor (undefined for sequence 0) */
  parent?: CheckpointId;
  /** Checkpoint this was forked/resumed from, when different from parent */
  base?: CheckpointId;
  /** Original checkpoint for a series of retries (preserve failure context) */
  source?: CheckpointId;
}

/** Snapshot integrity */
export interface CheckpointHash {
  /** SHA-256 of canonical serialized state */
  sha256: string;
  /** Byte count of the serialized state */
  byteCount: number;
}

/** Full checkpoint record */
export interface CheckpointManifest {
  id: CheckpointId;
  lineage: CheckpointLineage;
  hash: CheckpointHash;
  /** ISO 8601 timestamp */
  createdAt: string;
  /** Agent state snapshot location (opaque storage key) */
  storageKey: string;
  /** Logical label for display (e.g. "after tool call 3") */
  label?: string;
  /** Forward-compatible metadata */
  metadata?: Record<string, unknown>;
}

/** Checkpoint restore options */
export interface RestoreOptions {
  /** Create fresh agent identity (new process, cleared caches) */
  freshIdentity: boolean;
  /** Skip hash verification (faster but unsafe) */
  skipVerification?: boolean;
}

/**
 * Compute SHA-256 hash of checkpoint state
 * State must be in canonical form: sorted keys, no whitespace, UTF-8
 */
export function hashCheckpointState(canonicalState: string): CheckpointHash {
  const buffer = Buffer.from(canonicalState, "utf-8");
  const sha256 = createHash("sha256").update(buffer).digest("hex");
  return {
    sha256,
    byteCount: buffer.length,
  };
}

/**
 * Verify checkpoint integrity before restore
 */
export function verifyCheckpoint(
  manifest: CheckpointManifest,
  actualState: string,
): { valid: boolean; error?: string } {
  const actualHash = hashCheckpointState(actualState);

  if (actualHash.sha256 !== manifest.hash.sha256) {
    return {
      valid: false,
      error: `Hash mismatch: expected ${manifest.hash.sha256}, got ${actualHash.sha256}`,
    };
  }

  if (actualHash.byteCount !== manifest.hash.byteCount) {
    return {
      valid: false,
      error: `Size mismatch: expected ${manifest.hash.byteCount} bytes, got ${actualHash.byteCount}`,
    };
  }

  return { valid: true };
}

/**
 * Safe prune: determine which checkpoints can be deleted
 *
 * Keep:
 * - Latest checkpoint per run
 * - Any checkpoint referenced as base/source by a kept checkpoint
 * - Checkpoints newer than the retention window
 *
 * Everything else is safe to prune.
 */
export interface PrunePolicy {
  /** Keep checkpoints newer than this (milliseconds) */
  retentionMs: number;
  /** Always keep the latest N checkpoints per run */
  keepLatestPerRun: number;
  /** Keep checkpoints at regular intervals (e.g. every 10th) */
  keepEveryNth?: number;
}

export interface PruneResult {
  /** Checkpoints that can be safely deleted */
  prunable: readonly CheckpointId[];
  /** Checkpoints that must be kept */
  retained: readonly CheckpointId[];
  /** Reason each retained checkpoint was kept */
  retentionReasons: ReadonlyMap<string, string>;
}

/**
 * Compute safe prune set for a collection of checkpoints
 */
export function computePruneSet(
  manifests: readonly CheckpointManifest[],
  policy: PrunePolicy,
  nowMs: number = Date.now(),
): PruneResult {
  const retained = new Map<string, string>(); // checkpoint key -> retention reason
  const checkpointKey = (id: CheckpointId) => `${id.runId}:${id.sequence}`;

  // Group by run
  const byRun = new Map<string, CheckpointManifest[]>();
  for (const manifest of manifests) {
    const runManifests = byRun.get(manifest.id.runId) || [];
    runManifests.push(manifest);
    byRun.set(manifest.id.runId, runManifests);
  }

  // Sort each run by sequence
  for (const [runId, runManifests] of byRun) {
    runManifests.sort((a, b) => a.id.sequence - b.id.sequence);
    byRun.set(runId, runManifests);
  }

  // Rule 1: Keep latest N per run
  for (const [runId, runManifests] of byRun) {
    const keep = runManifests.slice(-policy.keepLatestPerRun);
    for (const manifest of keep) {
      retained.set(checkpointKey(manifest.id), `latest in run ${runId}`);
    }
  }

  // Rule 2: Keep checkpoints within retention window
  const retentionThreshold = nowMs - policy.retentionMs;
  for (const manifest of manifests) {
    const createdMs = new Date(manifest.createdAt).getTime();
    if (createdMs >= retentionThreshold) {
      const key = checkpointKey(manifest.id);
      if (!retained.has(key)) {
        retained.set(key, "within retention window");
      }
    }
  }

  // Rule 3: Keep every Nth checkpoint if specified
  if (policy.keepEveryNth) {
    for (const [_runId, runManifests] of byRun) {
      for (let i = 0; i < runManifests.length; i += policy.keepEveryNth) {
        const manifest = runManifests[i];
        const key = checkpointKey(manifest.id);
        if (!retained.has(key)) {
          retained.set(key, `interval checkpoint (every ${policy.keepEveryNth}th)`);
        }
      }
    }
  }

  // Rule 4: Keep checkpoints referenced as base/source by retained checkpoints
  let added = true;
  while (added) {
    added = false;
    for (const manifest of manifests) {
      const key = checkpointKey(manifest.id);
      if (retained.has(key)) {
        // This checkpoint is kept; check if it references others
        if (manifest.lineage.base) {
          const baseKey = checkpointKey(manifest.lineage.base);
          if (!retained.has(baseKey)) {
            retained.set(baseKey, `base for ${key}`);
            added = true;
          }
        }
        if (manifest.lineage.source) {
          const sourceKey = checkpointKey(manifest.lineage.source);
          if (!retained.has(sourceKey)) {
            retained.set(sourceKey, `source for ${key}`);
            added = true;
          }
        }
      }
    }
  }

  // Everything not retained is prunable
  const prunable: CheckpointId[] = [];
  for (const manifest of manifests) {
    const key = checkpointKey(manifest.id);
    if (!retained.has(key)) {
      prunable.push(manifest.id);
    }
  }

  return {
    prunable,
    retained: manifests.filter((m) => retained.has(checkpointKey(m.id))).map((m) => m.id),
    retentionReasons: retained,
  };
}

/**
 * Create a checkpoint manifest for a new checkpoint
 */
export function createCheckpointManifest(params: {
  runId: string;
  sequence: number;
  canonicalState: string;
  storageKey: string;
  lineage?: CheckpointLineage;
  label?: string;
  metadata?: Record<string, unknown>;
}): CheckpointManifest {
  return {
    id: {
      runId: params.runId,
      sequence: params.sequence,
    },
    lineage: params.lineage || {},
    hash: hashCheckpointState(params.canonicalState),
    createdAt: new Date().toISOString(),
    storageKey: params.storageKey,
    label: params.label,
    metadata: params.metadata,
  };
}

/**
 * Check if checkpoint A is an ancestor of checkpoint B
 */
export function isAncestor(
  manifests: readonly CheckpointManifest[],
  ancestorId: CheckpointId,
  descendantId: CheckpointId,
): boolean {
  const checkpointKey = (id: CheckpointId) => `${id.runId}:${id.sequence}`;
  const manifestMap = new Map(manifests.map((m) => [checkpointKey(m.id), m]));

  let current: CheckpointId | undefined = descendantId;
  const visited = new Set<string>();

  while (current) {
    const key = checkpointKey(current);
    if (key === checkpointKey(ancestorId)) {
      return true;
    }

    if (visited.has(key)) {
      // Cycle detected (should never happen but be defensive)
      return false;
    }
    visited.add(key);

    const manifest = manifestMap.get(key);
    if (!manifest) {
      return false;
    }

    // Follow parent lineage
    current = manifest.lineage.parent;
  }

  return false;
}
