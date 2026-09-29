import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompactionCoordinator } from "../../src/session/compaction-coordinator.js";
import { SessionTree } from "../../src/session/session-tree.js";

describe("CompactionCoordinator", () => {
  let coordinator: CompactionCoordinator;
  let tree: SessionTree;

  beforeEach(() => {
    vi.useFakeTimers();
    coordinator = new CompactionCoordinator(30000, 10000);
    tree = new SessionTree();
  });

  afterEach(() => {
    coordinator.shutdown();
    vi.useRealTimers();
  });

  describe("Lease Acquisition", () => {
    it("should acquire new lease", async () => {
      const result = await coordinator.acquireLease("session-1", "worker-1");

      expect(result.ok).toBe(true);
      expect(result.value).toBeDefined();
      expect(result.value!.sessionId).toBe("session-1");
      expect(result.value!.holder).toBe("worker-1");
      expect(result.value!.leaseId).toBeDefined();
    });

    it("should reject lease when already held by another", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const result = await coordinator.acquireLease("session-1", "worker-2");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Lease held by worker-1");
    });

    it("should extend lease for same holder", async () => {
      const first = await coordinator.acquireLease("session-1", "worker-1");
      expect(first.ok).toBe(true);

      const second = await coordinator.acquireLease("session-1", "worker-1");
      expect(second.ok).toBe(true);
      expect(second.value!.leaseId).toBe(first.value!.leaseId);
    });

    it("should allow acquisition after lease expires", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // Fast-forward past lease expiry
      vi.setSystemTime(new Date(start.getTime() + 31000));

      const result = await coordinator.acquireLease("session-1", "worker-2");
      expect(result.ok).toBe(true);
      expect(result.value!.holder).toBe("worker-2");
    });

    it("should create lease with correct expiry time", async () => {
      const now = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(now);

      const result = await coordinator.acquireLease("session-1", "worker-1");

      expect(result.ok).toBe(true);
      const expiresAt = new Date(result.value!.expiresAt);
      expect(expiresAt.getTime() - now.getTime()).toBe(30000);
    });
  });

  describe("Lease Release", () => {
    it("should release lease", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const result = await coordinator.releaseLease("session-1", "worker-1");
      expect(result.ok).toBe(true);

      // Should be able to acquire again
      const newLease = await coordinator.acquireLease("session-1", "worker-2");
      expect(newLease.ok).toBe(true);
    });

    it("should reject release from non-holder", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const result = await coordinator.releaseLease("session-1", "worker-2");
      expect(result.ok).toBe(false);
    });

    it("should be idempotent for already released", async () => {
      const result = await coordinator.releaseLease("session-1", "worker-1");
      expect(result.ok).toBe(true);
    });
  });

  describe("Heartbeat", () => {
    it("should extend lease via heartbeat", async () => {
      const result = await coordinator.acquireLease("session-1", "worker-1");
      expect(result.ok).toBe(true);

      const originalExpiry = new Date(result.value!.expiresAt);

      // Advance past first heartbeat interval
      vi.advanceTimersByTime(10000);

      const _cursor = coordinator.getCursor("session-1");
      // Lease should still be valid and extended
      const newLease = await coordinator.acquireLease("session-1", "worker-1");
      expect(newLease.ok).toBe(true);

      const newExpiry = new Date(newLease.value!.expiresAt);
      expect(newExpiry.getTime()).toBeGreaterThan(originalExpiry.getTime());
    });

    it("should stop heartbeat after release", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.releaseLease("session-1", "worker-1");

      // Advance past heartbeat interval
      vi.advanceTimersByTime(10000);

      // Lease should not exist
      const result = await coordinator.acquireLease("session-1", "worker-2");
      expect(result.ok).toBe(true);
      expect(result.value!.holder).toBe("worker-2");
    });
  });

  describe("Cursor Management", () => {
    it("should get cursor", () => {
      const cursor = coordinator.getCursor("session-1");
      expect(cursor).toBeUndefined();
    });

    it("should update cursor with CAS", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const result = coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");

      expect(result.ok).toBe(true);
      expect(result.value!.cursor).toBe("cursor-1");
      expect(result.value!.compactedUpTo).toBe(10);
      expect(result.value!.version).toBe(1);
    });

    it("should reject cursor update without lease", async () => {
      const result = coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Not the lease holder");
    });

    it("should reject cursor update with wrong holder", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const result = coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-2");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Not the lease holder");
    });

    it("should reject cursor update with expired lease", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // Fast-forward past lease expiry
      vi.setSystemTime(new Date(start.getTime() + 31000));

      const result = coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Lease expired");
    });

    it("should enforce CAS version check", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      // First update
      coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");

      // Second update with wrong version
      const result = coordinator.updateCursor("session-1", "cursor-2", 20, 99, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Version mismatch");
      expect(result.currentVersion).toBe(1);
    });

    it("should allow cursor update with correct version", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const first = coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");
      expect(first.ok).toBe(true);

      const second = coordinator.updateCursor("session-1", "cursor-2", 20, 1, "worker-1");
      expect(second.ok).toBe(true);
      expect(second.value!.version).toBe(2);
    });

    it("should reject backward cursor movement", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "cursor-1", 20, null, "worker-1");

      const result = coordinator.updateCursor("session-1", "cursor-2", 10, 1, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Cannot move cursor backward");
    });

    it("should allow same position cursor update", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "cursor-1", 20, null, "worker-1");

      const result = coordinator.updateCursor("session-1", "cursor-2", 20, 1, "worker-1");

      expect(result.ok).toBe(true);
    });

    it("should track lease holder in cursor", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");

      const cursor = coordinator.getCursor("session-1");
      expect(cursor!.leaseHolder).toBe("worker-1");
      expect(cursor!.leaseExpiry).toBeDefined();
    });
  });

  describe("Contiguous Verification", () => {
    it("should verify contiguous sequence", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      const result = coordinator.verifyContiguous(tree, 1, 3);

      expect(result.ok).toBe(true);
      expect(result.gaps).toHaveLength(0);
    });

    it("should detect gaps in sequence", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3

      // Simulate gap by removing entry
      (tree as any).sequenceIndex.delete(2);

      const result = coordinator.verifyContiguous(tree, 1, 3);

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([2]);
    });

    it("should detect multiple gaps", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3
      tree.appendParent("session-1", null); // seq 4
      tree.appendParent("session-1", null); // seq 5

      (tree as any).sequenceIndex.delete(2);
      (tree as any).sequenceIndex.delete(4);

      const result = coordinator.verifyContiguous(tree, 1, 5);

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([2, 4]);
    });

    it("should verify partial range", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3
      tree.appendParent("session-1", null); // seq 4

      const result = coordinator.verifyContiguous(tree, 2, 3);

      expect(result.ok).toBe(true);
      expect(result.gaps).toHaveLength(0);
    });
  });

  describe("Compaction Attempt", () => {
    it("should successfully compact with retry", async () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      const result = await coordinator.attemptCompaction(tree, "session-1", 3, "worker-1");

      expect(result.ok).toBe(true);
      expect(result.cursor).toBeDefined();
      expect(result.compactedUpTo).toBe(3);
    });

    it("should fail on gaps without retry", async () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      (tree as any).sequenceIndex.delete(2);

      const result = await coordinator.attemptCompaction(tree, "session-1", 3, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([2]);
      expect(result.shouldRetry).toBe(false);
    });

    it("should retry on lease conflict", async () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      // Another worker holds lease
      await coordinator.acquireLease("session-1", "worker-1");

      const result = await coordinator.attemptCompaction(tree, "session-1", 2, "worker-2", 1);

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Max retries");
    });

    it("should update cursor after successful compaction", async () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      await coordinator.attemptCompaction(tree, "session-1", 2, "worker-1");

      const cursor = coordinator.getCursor("session-1");
      expect(cursor).toBeDefined();
      expect(cursor!.compactedUpTo).toBe(2);
    });

    it("should compact from previous cursor", async () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      // First compaction
      await coordinator.attemptCompaction(tree, "session-1", 2, "worker-1");

      // Second compaction should verify from seq 3
      const result = await coordinator.attemptCompaction(tree, "session-1", 4, "worker-1");

      expect(result.ok).toBe(true);
      expect(result.compactedUpTo).toBe(4);
    });
  });

  describe("Gap Handling", () => {
    it("should handle fail strategy", () => {
      const result = coordinator.handleGaps([2, 4], "fail");

      expect(result.ok).toBe(false);
      expect(result.action).toContain("Fail compaction");
    });

    it("should handle skip strategy", () => {
      const result = coordinator.handleGaps([3, 5], "skip");

      expect(result.ok).toBe(true);
      expect(result.action).toContain("Skip gaps and compact up to 2");
    });

    it("should handle wait strategy", () => {
      const result = coordinator.handleGaps([2], "wait");

      expect(result.ok).toBe(false);
      expect(result.action).toContain("Wait for gaps");
    });

    it("should handle no gaps", () => {
      const result = coordinator.handleGaps([], "fail");

      expect(result.ok).toBe(true);
      expect(result.action).toBe("none");
    });
  });

  describe("Lease Cleanup", () => {
    it("should cleanup expired leases", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.acquireLease("session-2", "worker-2");

      // Fast-forward past expiry
      vi.setSystemTime(new Date(start.getTime() + 31000));

      const cleaned = coordinator.cleanupExpiredLeases();

      expect(cleaned).toBe(2);

      // Should be able to acquire both
      const result1 = await coordinator.acquireLease("session-1", "worker-3");
      const result2 = await coordinator.acquireLease("session-2", "worker-3");

      expect(result1.ok).toBe(true);
      expect(result2.ok).toBe(true);
    });

    it("should not cleanup active leases", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      // Don't advance past expiry
      vi.advanceTimersByTime(10000);

      const cleaned = coordinator.cleanupExpiredLeases();

      expect(cleaned).toBe(0);
    });
  });

  describe("Shutdown", () => {
    it("should stop all heartbeats on shutdown", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.acquireLease("session-2", "worker-2");

      coordinator.shutdown();

      // Heartbeats should not extend leases
      vi.advanceTimersByTime(10000);

      // Leases should be cleared
      const result = await coordinator.acquireLease("session-1", "worker-3");
      expect(result.ok).toBe(true);
    });

    it("should clear all state", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      coordinator.updateCursor("session-1", "cursor-1", 10, null, "worker-1");

      coordinator.shutdown();

      const cursor = coordinator.getCursor("session-1");
      expect(cursor).toBeUndefined();
    });
  });

  describe("Concurrent Operations", () => {
    it("should handle concurrent lease attempts", async () => {
      const results = await Promise.all([
        coordinator.acquireLease("session-1", "worker-1"),
        coordinator.acquireLease("session-1", "worker-2"),
        coordinator.acquireLease("session-1", "worker-3"),
      ]);

      const successful = results.filter((r) => r.ok);
      expect(successful).toHaveLength(1);

      const failed = results.filter((r) => !r.ok);
      expect(failed).toHaveLength(2);
    });

    it("should serialize cursor updates", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const first = coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");
      const second = coordinator.updateCursor("session-1", "c2", 20, null, "worker-1");

      expect(first.ok).toBe(true);
      expect(second.ok).toBe(false); // Wrong version
    });
  });

  describe("Edge Cases", () => {
    it("should reject invalid lease configuration", () => {
      expect(() => new CompactionCoordinator(10000, 10000)).toThrow();
      expect(() => new CompactionCoordinator(5000, 10000)).toThrow();
    });

    it("should handle empty session tree", async () => {
      const result = await coordinator.attemptCompaction(tree, "session-1", 0, "worker-1");

      expect(result.ok).toBe(true);
    });

    it("should generate unique cursor IDs", async () => {
      tree.appendParent("session-1", null);

      await coordinator.acquireLease("session-1", "worker-1");

      const r1 = coordinator.updateCursor("session-1", "c1", 1, null, "worker-1");
      await coordinator.releaseLease("session-1", "worker-1");

      await coordinator.acquireLease("session-1", "worker-1");
      const r2 = coordinator.updateCursor("session-1", "c2", 1, 1, "worker-1");

      expect(r1.value!.cursor).not.toBe(r2.value!.cursor);
    });

    it("should handle rapid lease acquire/release cycles", async () => {
      for (let i = 0; i < 10; i++) {
        const acquire = await coordinator.acquireLease("session-1", `worker-${i}`);
        expect(acquire.ok).toBe(true);

        const release = await coordinator.releaseLease("session-1", `worker-${i}`);
        expect(release.ok).toBe(true);
      }
    });
  });
});
