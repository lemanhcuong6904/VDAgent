import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompactionCoordinator } from "../../src/session/compaction-coordinator.js";
import { SessionTree } from "../../src/session/session-tree.js";

describe("CompactionCoordinator - Edge Cases", () => {
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

  describe("CAS Version Precision", () => {
    it("should enforce strict version matching", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // Create initial cursor
      const r1 = coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");
      expect(r1.ok).toBe(true);
      expect(r1.currentVersion).toBe(1);

      // Try with version 0 (should fail)
      const r2 = coordinator.updateCursor("session-1", "c2", 20, 0, "worker-1");
      expect(r2.ok).toBe(false);
      expect(r2.currentVersion).toBe(1);

      // Try with version 2 (should fail)
      const r3 = coordinator.updateCursor("session-1", "c3", 20, 2, "worker-1");
      expect(r3.ok).toBe(false);
      expect(r3.currentVersion).toBe(1);

      // Correct version should work
      const r4 = coordinator.updateCursor("session-1", "c4", 20, 1, "worker-1");
      expect(r4.ok).toBe(true);
      expect(r4.currentVersion).toBe(2);
    });

    it("should handle version wraparound safely", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      // Simulate many updates
      let version = null;
      for (let i = 1; i <= 100; i++) {
        const result = coordinator.updateCursor("session-1", `cursor-${i}`, i, version, "worker-1");
        expect(result.ok).toBe(true);
        version = result.currentVersion!;
      }

      expect(version).toBe(100);

      const cursor = coordinator.getCursor("session-1");
      expect(cursor!.version).toBe(100);
    });

    it("should reject null version when cursor exists", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");

      const result = coordinator.updateCursor("session-1", "c2", 20, null, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("expected null version");
    });

    it("should reject non-null version when cursor does not exist", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      const result = coordinator.updateCursor("session-1", "c1", 10, 5, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("does not exist");
    });
  });

  describe("Monotonicity Enforcement", () => {
    it("should prevent backward cursor movement", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "c1", 100, null, "worker-1");

      const result = coordinator.updateCursor("session-1", "c2", 50, 1, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("backward");
    });

    it("should allow same position cursor update", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "c1", 100, null, "worker-1");

      const result = coordinator.updateCursor("session-1", "c2", 100, 1, "worker-1");

      expect(result.ok).toBe(true);
    });

    it("should allow forward movement only", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "c1", 50, null, "worker-1");

      const r1 = coordinator.updateCursor("session-1", "c2", 51, 1, "worker-1");
      expect(r1.ok).toBe(true);

      const r2 = coordinator.updateCursor("session-1", "c3", 100, 2, "worker-1");
      expect(r2.ok).toBe(true);

      const r3 = coordinator.updateCursor("session-1", "c4", 101, 3, "worker-1");
      expect(r3.ok).toBe(true);
    });
  });

  describe("Lease Expiry Edge Cases", () => {
    it("should reject cursor update at exact expiry moment", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // Move to exact expiry time
      vi.setSystemTime(new Date(start.getTime() + 30000));

      const result = coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("expired");
    });

    it("should allow cursor update just before expiry", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // Move to 1ms before expiry
      vi.setSystemTime(new Date(start.getTime() + 29999));

      const result = coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");

      expect(result.ok).toBe(true);
    });

    it("should handle lease acquisition at boundary", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      const lease1 = await coordinator.acquireLease("session-1", "worker-1");
      expect(lease1.ok).toBe(true);

      // Move to exact expiry
      vi.setSystemTime(new Date(start.getTime() + 30000));

      const lease2 = await coordinator.acquireLease("session-1", "worker-2");
      expect(lease2.ok).toBe(true);
      expect(lease2.value!.holder).toBe("worker-2");
    });

    it("should reject at 1ms before expiry for new holder", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // 1ms before expiry
      vi.setSystemTime(new Date(start.getTime() + 29999));

      const result = await coordinator.acquireLease("session-1", "worker-2");
      expect(result.ok).toBe(false);
    });
  });

  describe("Gap Detection Precision", () => {
    it("should detect single gap at beginning", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2

      (tree as any).sequenceIndex.delete(1);

      const result = coordinator.verifyContiguous(tree, 1, 2);

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([1]);
    });

    it("should detect single gap at end", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3

      (tree as any).sequenceIndex.delete(3);

      const result = coordinator.verifyContiguous(tree, 1, 3);

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([3]);
    });

    it("should detect gap in middle", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3

      (tree as any).sequenceIndex.delete(2);

      const result = coordinator.verifyContiguous(tree, 1, 3);

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([2]);
    });

    it("should detect all gaps in range", () => {
      for (let i = 1; i <= 10; i++) {
        tree.appendParent("session-1", null);
      }

      // Remove even sequences
      for (let i = 2; i <= 10; i += 2) {
        (tree as any).sequenceIndex.delete(i);
      }

      const result = coordinator.verifyContiguous(tree, 1, 10);

      expect(result.ok).toBe(false);
      expect(result.gaps).toEqual([2, 4, 6, 8, 10]);
    });

    it("should handle single-entry range", () => {
      tree.appendParent("session-1", null); // seq 1

      const result = coordinator.verifyContiguous(tree, 1, 1);

      expect(result.ok).toBe(true);
      expect(result.gaps).toHaveLength(0);
    });

    it("should handle empty range correctly", () => {
      const result = coordinator.verifyContiguous(tree, 1, 0);

      expect(result.ok).toBe(true);
      expect(result.gaps).toHaveLength(0);
    });
  });

  describe("Retry Behavior", () => {
    it("should retry on transient lease conflict", async () => {
      vi.useRealTimers(); // Use real timers for retry testing

      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      // Hold lease briefly then release
      const lease = await coordinator.acquireLease("session-1", "worker-1");
      expect(lease.ok).toBe(true);

      // Start compaction attempt in background
      const compactionPromise = coordinator.attemptCompaction(tree, "session-1", 2, "worker-2", 3);

      // Release after first retry
      await new Promise((resolve) => setTimeout(resolve, 150));
      await coordinator.releaseLease("session-1", "worker-1");

      const result = await compactionPromise;
      expect(result.ok).toBe(true);

      vi.useFakeTimers(); // Restore fake timers
    });

    it("should not retry on gaps", async () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      (tree as any).sequenceIndex.delete(2);

      const result = await coordinator.attemptCompaction(tree, "session-1", 3, "worker-1", 5);

      expect(result.ok).toBe(false);
      expect(result.shouldRetry).toBe(false);
    });

    it("should respect max retries", async () => {
      vi.useRealTimers(); // Use real timers for retry testing

      tree.appendParent("session-1", null);

      // Hold lease throughout
      await coordinator.acquireLease("session-1", "worker-1");

      const result = await coordinator.attemptCompaction(tree, "session-1", 1, "worker-2", 2);

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("Max retries");

      vi.useFakeTimers(); // Restore fake timers
    });
  });

  describe("Heartbeat Behavior", () => {
    it("should maintain lease through heartbeats", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      // Advance through multiple heartbeat intervals
      for (let i = 1; i <= 5; i++) {
        vi.advanceTimersByTime(10000);
        vi.setSystemTime(new Date(start.getTime() + i * 10000));
      }

      // Lease should still be valid (heartbeats extended it)
      const result = await coordinator.acquireLease("session-1", "worker-1");
      expect(result.ok).toBe(true);
    });

    it("should stop heartbeat after release", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.releaseLease("session-1", "worker-1");

      // Advance past what would have been heartbeat
      vi.advanceTimersByTime(10000);

      // Should be able to acquire with different holder
      const result = await coordinator.acquireLease("session-1", "worker-2");
      expect(result.ok).toBe(true);
      expect(result.value!.holder).toBe("worker-2");
    });

    it("should stop heartbeat on shutdown", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.shutdown();

      // Advance timers
      vi.advanceTimersByTime(10000);

      // Create new coordinator and check lease is gone
      const newCoordinator = new CompactionCoordinator(30000, 10000);
      const result = await newCoordinator.acquireLease("session-1", "worker-2");
      expect(result.ok).toBe(true);

      newCoordinator.shutdown();
    });
  });

  describe("Cursor State Consistency", () => {
    it("should maintain cursor after failed update", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");

      // Failed update with wrong version
      const failed = coordinator.updateCursor("session-1", "c2", 20, 99, "worker-1");
      expect(failed.ok).toBe(false);

      // Original cursor unchanged
      const cursor = coordinator.getCursor("session-1");
      expect(cursor!.cursor).toBe("c1");
      expect(cursor!.compactedUpTo).toBe(10);
      expect(cursor!.version).toBe(1);
    });

    it("should track lease holder in cursor", async () => {
      await coordinator.acquireLease("session-1", "worker-1");

      coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");

      const cursor = coordinator.getCursor("session-1");
      expect(cursor!.leaseHolder).toBe("worker-1");
      expect(cursor!.leaseExpiry).toBeDefined();
    });

    it("should update cursor metadata on each change", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");

      const r1 = coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");
      const timestamp1 = r1.value!.timestamp;

      // Advance time
      vi.setSystemTime(new Date(start.getTime() + 5000));

      const r2 = coordinator.updateCursor("session-1", "c2", 20, 1, "worker-1");
      const timestamp2 = r2.value!.timestamp;

      expect(new Date(timestamp2).getTime()).toBeGreaterThan(new Date(timestamp1).getTime());
    });
  });

  describe("Multiple Session Isolation", () => {
    it("should isolate leases per session", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.acquireLease("session-2", "worker-2");

      const cursor1 = coordinator.getCursor("session-1");
      const cursor2 = coordinator.getCursor("session-2");

      expect(cursor1).toBeUndefined();
      expect(cursor2).toBeUndefined();

      // Each can update independently
      coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");
      coordinator.updateCursor("session-2", "c2", 20, null, "worker-2");

      const updated1 = coordinator.getCursor("session-1");
      const updated2 = coordinator.getCursor("session-2");

      expect(updated1!.compactedUpTo).toBe(10);
      expect(updated2!.compactedUpTo).toBe(20);
    });

    it("should not interfere with each other's versions", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.acquireLease("session-2", "worker-2");

      // Both start at version 1
      coordinator.updateCursor("session-1", "c1", 10, null, "worker-1");
      coordinator.updateCursor("session-2", "c2", 20, null, "worker-2");

      const c1 = coordinator.getCursor("session-1");
      const c2 = coordinator.getCursor("session-2");

      expect(c1!.version).toBe(1);
      expect(c2!.version).toBe(1);

      // Each can progress independently
      coordinator.updateCursor("session-1", "c3", 15, 1, "worker-1");
      coordinator.updateCursor("session-1", "c4", 20, 2, "worker-1");

      coordinator.updateCursor("session-2", "c5", 25, 1, "worker-2");

      expect(coordinator.getCursor("session-1")!.version).toBe(3);
      expect(coordinator.getCursor("session-2")!.version).toBe(2);
    });
  });

  describe("Cleanup Edge Cases", () => {
    it("should cleanup only expired leases", async () => {
      const start = new Date("2024-01-01T00:00:00Z");
      vi.setSystemTime(start);

      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.acquireLease("session-2", "worker-2");

      // Advance to expire only first lease
      vi.setSystemTime(new Date(start.getTime() + 30000));
      await coordinator.acquireLease("session-2", "worker-2"); // Extend session-2

      const cleaned = coordinator.cleanupExpiredLeases();

      expect(cleaned).toBe(1);

      // session-1 should be available
      const r1 = await coordinator.acquireLease("session-1", "worker-3");
      expect(r1.ok).toBe(true);

      // session-2 should still be held
      const r2 = await coordinator.acquireLease("session-2", "worker-3");
      expect(r2.ok).toBe(false);
    });

    it("should handle cleanup with no leases", () => {
      const cleaned = coordinator.cleanupExpiredLeases();
      expect(cleaned).toBe(0);
    });

    it("should handle cleanup with all active leases", async () => {
      await coordinator.acquireLease("session-1", "worker-1");
      await coordinator.acquireLease("session-2", "worker-2");

      const cleaned = coordinator.cleanupExpiredLeases();
      expect(cleaned).toBe(0);
    });
  });
});
