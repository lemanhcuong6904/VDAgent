/**
 * Checkpoint Manifest Tests
 * M9.6: Lineage tracking, hash verification, and safe pruning tests
 */

import { describe, expect, it } from "vitest";
import {
  type CheckpointId,
  type CheckpointManifest,
  computePruneSet,
  createCheckpointManifest,
  hashCheckpointState,
  isAncestor,
  type PrunePolicy,
  verifyCheckpoint,
} from "../src/checkpoint-manifest.js";

describe("M9.6: Checkpoint Hash and Verification", () => {
  it("should compute consistent SHA-256 hash", () => {
    const state = JSON.stringify({ counter: 42, status: "running" });
    const hash1 = hashCheckpointState(state);
    const hash2 = hashCheckpointState(state);

    expect(hash1.sha256).toBe(hash2.sha256);
    expect(hash1.byteCount).toBe(hash2.byteCount);
    expect(hash1.sha256).toMatch(/^[a-f0-9]{64}$/);
  });

  it("should produce different hashes for different states", () => {
    const state1 = JSON.stringify({ counter: 42 });
    const state2 = JSON.stringify({ counter: 43 });

    const hash1 = hashCheckpointState(state1);
    const hash2 = hashCheckpointState(state2);

    expect(hash1.sha256).not.toBe(hash2.sha256);
  });

  it("should verify valid checkpoint", () => {
    const state = JSON.stringify({ data: "test" });
    const manifest = createCheckpointManifest({
      runId: "run-1",
      sequence: 1,
      canonicalState: state,
      storageKey: "s3://bucket/checkpoint-1",
    });

    const verification = verifyCheckpoint(manifest, state);

    expect(verification.valid).toBe(true);
    expect(verification.error).toBeUndefined();
  });

  it("should reject checkpoint with hash mismatch", () => {
    const originalState = JSON.stringify({ data: "original" });
    const tamperedState = JSON.stringify({ data: "tampered" });

    const manifest = createCheckpointManifest({
      runId: "run-1",
      sequence: 1,
      canonicalState: originalState,
      storageKey: "s3://bucket/checkpoint-1",
    });

    const verification = verifyCheckpoint(manifest, tamperedState);

    expect(verification.valid).toBe(false);
    expect(verification.error).toContain("Hash mismatch");
  });

  it("should reject checkpoint with size mismatch", () => {
    const state = JSON.stringify({ data: "test" });
    const manifest = createCheckpointManifest({
      runId: "run-1",
      sequence: 1,
      canonicalState: state,
      storageKey: "s3://bucket/checkpoint-1",
    });

    // Manually corrupt the byte count
    const corruptedManifest = {
      ...manifest,
      hash: {
        ...manifest.hash,
        byteCount: manifest.hash.byteCount + 10,
      },
    };

    const verification = verifyCheckpoint(corruptedManifest, state);

    expect(verification.valid).toBe(false);
    expect(verification.error).toContain("Size mismatch");
  });
});

describe("M9.6: Checkpoint Manifest Creation", () => {
  it("should create manifest with all fields", () => {
    const state = JSON.stringify({ counter: 5 });
    const manifest = createCheckpointManifest({
      runId: "run-123",
      sequence: 5,
      canonicalState: state,
      storageKey: "checkpoint-5.json",
      label: "after retry 3",
      metadata: { attempt: 3 },
    });

    expect(manifest.id.runId).toBe("run-123");
    expect(manifest.id.sequence).toBe(5);
    expect(manifest.storageKey).toBe("checkpoint-5.json");
    expect(manifest.label).toBe("after retry 3");
    expect(manifest.metadata).toEqual({ attempt: 3 });
    expect(manifest.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(manifest.hash.sha256).toBeTruthy();
  });

  it("should create manifest with lineage", () => {
    const state = JSON.stringify({ counter: 2 });
    const manifest = createCheckpointManifest({
      runId: "run-1",
      sequence: 2,
      canonicalState: state,
      storageKey: "checkpoint-2.json",
      lineage: {
        parent: { runId: "run-1", sequence: 1 },
        base: { runId: "run-1", sequence: 0 },
      },
    });

    expect(manifest.lineage.parent).toEqual({ runId: "run-1", sequence: 1 });
    expect(manifest.lineage.base).toEqual({ runId: "run-1", sequence: 0 });
  });

  it("should create manifest with empty lineage for sequence 0", () => {
    const state = JSON.stringify({ initial: true });
    const manifest = createCheckpointManifest({
      runId: "run-1",
      sequence: 0,
      canonicalState: state,
      storageKey: "checkpoint-0.json",
    });

    expect(manifest.lineage).toEqual({});
    expect(manifest.lineage.parent).toBeUndefined();
  });
});

describe("M9.6: Lineage Tracking", () => {
  it("should detect direct ancestry", () => {
    const manifests: CheckpointManifest[] = [
      createCheckpointManifest({
        runId: "run-1",
        sequence: 0,
        canonicalState: "{}",
        storageKey: "c0",
      }),
      createCheckpointManifest({
        runId: "run-1",
        sequence: 1,
        canonicalState: "{}",
        storageKey: "c1",
        lineage: { parent: { runId: "run-1", sequence: 0 } },
      }),
      createCheckpointManifest({
        runId: "run-1",
        sequence: 2,
        canonicalState: "{}",
        storageKey: "c2",
        lineage: { parent: { runId: "run-1", sequence: 1 } },
      }),
    ];

    expect(
      isAncestor(manifests, { runId: "run-1", sequence: 0 }, { runId: "run-1", sequence: 2 }),
    ).toBe(true);

    expect(
      isAncestor(manifests, { runId: "run-1", sequence: 1 }, { runId: "run-1", sequence: 2 }),
    ).toBe(true);
  });

  it("should return false for non-ancestors", () => {
    const manifests: CheckpointManifest[] = [
      createCheckpointManifest({
        runId: "run-1",
        sequence: 0,
        canonicalState: "{}",
        storageKey: "c0",
      }),
      createCheckpointManifest({
        runId: "run-1",
        sequence: 1,
        canonicalState: "{}",
        storageKey: "c1",
        lineage: { parent: { runId: "run-1", sequence: 0 } },
      }),
    ];

    expect(
      isAncestor(manifests, { runId: "run-1", sequence: 1 }, { runId: "run-1", sequence: 0 }),
    ).toBe(false);
  });

  it("should handle cross-run lineage via base", () => {
    const manifests: CheckpointManifest[] = [
      createCheckpointManifest({
        runId: "run-1",
        sequence: 5,
        canonicalState: "{}",
        storageKey: "c5",
      }),
      createCheckpointManifest({
        runId: "run-2",
        sequence: 0,
        canonicalState: "{}",
        storageKey: "c0-run2",
        lineage: { base: { runId: "run-1", sequence: 5 } },
      }),
    ];

    // Direct parent link doesn't exist, but base exists
    expect(
      isAncestor(manifests, { runId: "run-1", sequence: 5 }, { runId: "run-2", sequence: 0 }),
    ).toBe(false); // isAncestor follows parent chain only
  });
});

describe("M9.6: Safe Pruning", () => {
  const createTestManifest = (
    runId: string,
    sequence: number,
    ageMs: number,
    parent?: CheckpointId,
  ): CheckpointManifest => {
    return {
      id: { runId, sequence },
      lineage: parent ? { parent } : {},
      hash: { sha256: "abc123", byteCount: 100 },
      createdAt: new Date(Date.now() - ageMs).toISOString(),
      storageKey: `checkpoint-${runId}-${sequence}`,
    };
  };

  it("should keep latest N checkpoints per run", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 0, 10_000),
      createTestManifest("run-1", 1, 9_000, { runId: "run-1", sequence: 0 }),
      createTestManifest("run-1", 2, 8_000, { runId: "run-1", sequence: 1 }),
      createTestManifest("run-1", 3, 7_000, { runId: "run-1", sequence: 2 }),
      createTestManifest("run-1", 4, 6_000, { runId: "run-1", sequence: 3 }),
    ];

    const policy: PrunePolicy = {
      retentionMs: 5_000,
      keepLatestPerRun: 2,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // Latest 2 (seq 3, 4) should be kept
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 3 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 4 });

    // Older ones (seq 0, 1, 2) can be pruned
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 0 });
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 1 });
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 2 });
  });

  it("should keep checkpoints within retention window", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 0, 100_000), // 100s old, outside retention
      createTestManifest("run-1", 1, 40_000), // 40s old, within retention
      createTestManifest("run-1", 2, 10_000), // 10s old, within retention
    ];

    const policy: PrunePolicy = {
      retentionMs: 60_000, // 60 seconds
      keepLatestPerRun: 1,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // seq 1 and 2 are within 60s window
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 1 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 2 });

    // seq 0 is outside window and not latest
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 0 });
  });

  it("should keep checkpoints referenced as base", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 10, 200_000), // Old checkpoint from run-1
      createTestManifest("run-2", 0, 10_000), // Recent checkpoint that references run-1:10 as base
    ];

    // run-2:0 has run-1:10 as base
    manifests[1].lineage.base = { runId: "run-1", sequence: 10 };

    const policy: PrunePolicy = {
      retentionMs: 60_000,
      keepLatestPerRun: 1,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // run-1:10 should be kept because it's referenced as base by run-2:0
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 10 });
    expect(result.retained).toContainEqual({ runId: "run-2", sequence: 0 });
    expect(result.prunable).toHaveLength(0);
  });

  it("should keep checkpoints referenced as source", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 5, 200_000), // Old checkpoint
      createTestManifest("run-1", 6, 10_000), // Recent retry that references seq 5 as source
    ];

    manifests[1].lineage.source = { runId: "run-1", sequence: 5 };

    const policy: PrunePolicy = {
      retentionMs: 60_000,
      keepLatestPerRun: 1,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // seq 5 should be kept because it's the source for seq 6
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 5 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 6 });
  });

  it("should keep every Nth checkpoint when specified", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 0, 100_000),
      createTestManifest("run-1", 1, 100_000),
      createTestManifest("run-1", 2, 100_000),
      createTestManifest("run-1", 3, 100_000),
      createTestManifest("run-1", 4, 100_000),
      createTestManifest("run-1", 5, 100_000),
    ];

    const policy: PrunePolicy = {
      retentionMs: 10_000, // All are older than this
      keepLatestPerRun: 1, // Only seq 5 by this rule
      keepEveryNth: 2, // seq 0, 2, 4
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // seq 5 (latest), 0, 2, 4 (every 2nd) should be kept
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 0 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 2 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 4 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 5 });

    // seq 1, 3 can be pruned
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 1 });
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 3 });
  });

  it("should provide retention reasons", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 0, 50_000),
      createTestManifest("run-1", 1, 10_000),
    ];

    const policy: PrunePolicy = {
      retentionMs: 60_000,
      keepLatestPerRun: 1,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    expect(result.retentionReasons.get("run-1:1")).toContain("latest in run");
    expect(result.retentionReasons.get("run-1:0")).toContain("retention window");
  });

  it("should handle multiple runs independently", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 0, 100_000),
      createTestManifest("run-1", 1, 10_000),
      createTestManifest("run-2", 0, 100_000),
      createTestManifest("run-2", 1, 10_000),
    ];

    const policy: PrunePolicy = {
      retentionMs: 60_000,
      keepLatestPerRun: 1,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // Latest from each run should be kept
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 1 });
    expect(result.retained).toContainEqual({ runId: "run-2", sequence: 1 });

    // Old checkpoints can be pruned
    expect(result.prunable).toContainEqual({ runId: "run-1", sequence: 0 });
    expect(result.prunable).toContainEqual({ runId: "run-2", sequence: 0 });
  });

  it("should transitively keep base-of-base", () => {
    const nowMs = Date.now();
    const manifests: CheckpointManifest[] = [
      createTestManifest("run-1", 0, 300_000), // Very old
      createTestManifest("run-1", 5, 200_000), // Old, references run-1:0 as base
      createTestManifest("run-2", 0, 10_000), // Recent, references run-1:5 as base
    ];

    manifests[1].lineage.base = { runId: "run-1", sequence: 0 };
    manifests[2].lineage.base = { runId: "run-1", sequence: 5 };

    const policy: PrunePolicy = {
      retentionMs: 60_000,
      keepLatestPerRun: 1,
    };

    const result = computePruneSet(manifests, policy, nowMs);

    // All three should be kept due to transitive base references
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 0 });
    expect(result.retained).toContainEqual({ runId: "run-1", sequence: 5 });
    expect(result.retained).toContainEqual({ runId: "run-2", sequence: 0 });
    expect(result.prunable).toHaveLength(0);
  });
});

describe("M9.6: Forward Compatibility", () => {
  it("should preserve unknown metadata fields", () => {
    const state = JSON.stringify({ data: "test" });
    const manifest = createCheckpointManifest({
      runId: "run-1",
      sequence: 1,
      canonicalState: state,
      storageKey: "checkpoint-1",
      metadata: {
        customField: "value",
        experimentalFeature: true,
        unknownCounter: 42,
      },
    });

    expect(manifest.metadata).toEqual({
      customField: "value",
      experimentalFeature: true,
      unknownCounter: 42,
    });
  });
});
