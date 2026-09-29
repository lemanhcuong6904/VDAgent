import { beforeEach, describe, expect, it } from "vitest";
import { SessionTree } from "../../src/session/session-tree.js";

describe("SessionTree - Advanced Scenarios", () => {
  let tree: SessionTree;

  beforeEach(() => {
    tree = new SessionTree();
  });

  describe("Branch and Fork", () => {
    it("should create branch from parent", () => {
      const parent = tree.appendParent("session-1", null, { title: "Main" });
      const branch = tree.appendBranch("session-1", parent.entryId, "experiment-1", parent.entryId);

      expect(branch.type).toBe("branch");
      expect(branch.branchName).toBe("experiment-1");
      expect(branch.branchedFrom).toBe(parent.entryId);
    });

    it("should append content to branch", () => {
      const parent = tree.appendParent("session-1", null);
      const branch = tree.appendBranch("session-1", parent.entryId, "branch-1", parent.entryId);

      const leaf = tree.appendLeaf("session-1", branch.entryId, "user_message", {
        text: "Branch content",
      });

      expect(leaf.parentEntryId).toBe(branch.entryId);
    });

    it("should reconstruct branches correctly", () => {
      const parent = tree.appendParent("session-1", null);
      const branch1 = tree.appendBranch("session-1", parent.entryId, "b1", parent.entryId);
      const branch2 = tree.appendBranch("session-1", parent.entryId, "b2", parent.entryId);

      tree.appendLeaf("session-1", branch1.entryId, "user_message", "B1 content");
      tree.appendLeaf("session-1", branch2.entryId, "user_message", "B2 content");

      const reconstruction = tree.reconstructSession("session-1");

      expect(reconstruction.branches.size).toBe(2);
      expect(reconstruction.branches.has("b1")).toBe(true);
      expect(reconstruction.branches.has("b2")).toBe(true);
    });

    it("should handle nested branches", () => {
      const parent = tree.appendParent("session-1", null);
      const branch1 = tree.appendBranch("session-1", parent.entryId, "branch-1", parent.entryId);
      const branch2 = tree.appendBranch("session-1", branch1.entryId, "branch-2", branch1.entryId);

      tree.appendLeaf("session-1", branch2.entryId, "user_message", "Nested content");

      const reconstruction = tree.reconstructSession("session-1");
      expect(reconstruction.branches.size).toBe(2);
    });

    it("should fork session at specific point", () => {
      const p1 = tree.appendParent("session-1", null);
      const l1 = tree.appendLeaf("session-1", p1.entryId, "user_message", "Message 1");
      const _l2 = tree.appendLeaf("session-1", p1.entryId, "assistant_message", "Response 1");

      // Fork from l1
      const fork = tree.appendBranch("session-1", p1.entryId, "fork-1", l1.entryId);
      const forkLeaf = tree.appendLeaf("session-1", fork.entryId, "user_message", "Fork message");

      expect(fork.branchedFrom).toBe(l1.entryId);
      expect(forkLeaf.parentEntryId).toBe(fork.entryId);
    });

    it("should maintain parent chains across branches", () => {
      const parent = tree.appendParent("session-1", null);
      const branch = tree.appendBranch("session-1", parent.entryId, "b1", parent.entryId);
      const leaf = tree.appendLeaf("session-1", branch.entryId, "user_message", "Test");

      const chain = tree.getParentChain(leaf.entryId);

      expect(chain).toHaveLength(3);
      expect(chain[0]).toBe(parent);
      expect(chain[1]).toBe(branch);
      expect(chain[2]).toBe(leaf);
    });
  });

  describe("Restore and Reset", () => {
    it("should create reset entry", () => {
      const parent = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", parent.entryId, "user_message", "Message 1");
      tree.appendLeaf("session-1", parent.entryId, "assistant_message", "Response 1");

      const reset = tree.appendReset("session-1", parent.entryId, "Context reset");

      expect(reset.type).toBe("reset");
      expect(reset.reason).toBe("Context reset");
    });

    it("should preserve specified entries on reset", () => {
      const parent = tree.appendParent("session-1", null);
      const l1 = tree.appendLeaf("session-1", parent.entryId, "user_message", "Keep this");
      const _l2 = tree.appendLeaf("session-1", parent.entryId, "user_message", "Drop this");

      const reset = tree.appendReset("session-1", parent.entryId, "Partial reset", {
        preservedEntries: [l1.entryId],
      });

      expect(reset.preservedEntries).toEqual([l1.entryId]);
    });

    it("should reconstruct session with resets", () => {
      const parent = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", parent.entryId, "user_message", "Before");
      tree.appendReset("session-1", parent.entryId, "Reset 1");
      tree.appendLeaf("session-1", parent.entryId, "user_message", "After");
      tree.appendReset("session-1", parent.entryId, "Reset 2");

      const reconstruction = tree.reconstructSession("session-1");

      expect(reconstruction.resets).toHaveLength(2);
      expect(reconstruction.resets[0].reason).toBe("Reset 1");
      expect(reconstruction.resets[1].reason).toBe("Reset 2");
    });

    it("should restore from serialized log", () => {
      const p1 = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", p1.entryId, "user_message", "Message");
      tree.appendReset("session-1", p1.entryId, "Reset");

      const serialized = tree.serialize();
      const restored = SessionTree.deserialize(serialized);

      expect(restored.getCurrentSeq()).toBe(tree.getCurrentSeq());
      expect(restored.getAllEntries()).toHaveLength(tree.getAllEntries().length);
    });

    it("should handle restore with branches", () => {
      const parent = tree.appendParent("session-1", null);
      tree.appendBranch("session-1", parent.entryId, "branch-1", parent.entryId);
      tree.appendLeaf("session-1", parent.entryId, "user_message", "Main");

      const serialized = tree.serialize();
      const restored = SessionTree.deserialize(serialized);

      const reconstruction = restored.reconstructSession("session-1");
      expect(reconstruction.branches.size).toBe(1);
    });

    it("should handle restore with compactions", () => {
      const parent = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", parent.entryId, "user_message", "Message 1");
      tree.appendCompaction(
        "session-1",
        parent.entryId,
        1,
        "cursor-1",
        { summary: "Compacted" },
        [parent.entryId],
        100,
      );

      const serialized = tree.serialize();
      const restored = SessionTree.deserialize(serialized);

      const lastCompaction = restored.getLastCompaction("session-1");
      expect(lastCompaction).toBeDefined();
      expect(lastCompaction!.cursor).toBe("cursor-1");
    });
  });

  describe("Provider Failure Scenarios", () => {
    it("should handle missing entries in sequence", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3

      // Simulate provider failure - entry not persisted
      (tree as any).sequenceIndex.delete(2);

      const verification = tree.verifyContiguous();
      expect(verification.ok).toBe(false);
      expect(verification.gaps).toEqual([2]);
    });

    it("should detect gaps in restoration", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      const serialized = tree.serialize();

      // Simulate incomplete/corrupted restore
      const corrupted = serialized.filter((_, idx) => idx !== 1);
      const restored = SessionTree.deserialize(corrupted);

      const verification = restored.verifyContiguous();
      expect(verification.ok).toBe(false);
    });

    it("should handle partial branch persistence", () => {
      const parent = tree.appendParent("session-1", null);
      const branch = tree.appendBranch("session-1", parent.entryId, "b1", parent.entryId);
      tree.appendLeaf("session-1", branch.entryId, "user_message", "Content");

      // Remove branch entry but keep child
      (tree as any).entries.delete(branch.entryId);
      (tree as any).sequenceIndex.delete(branch.seqNum);

      const children = tree.getChildren(parent.entryId);
      expect(children.some((c) => c.type === "branch")).toBe(false);
    });

    it("should handle orphaned entries", () => {
      const parent = tree.appendParent("session-1", null);
      const leaf = tree.appendLeaf("session-1", parent.entryId, "user_message", "Test");

      // Remove parent
      (tree as any).entries.delete(parent.entryId);

      const chain = tree.getParentChain(leaf.entryId);
      expect(chain).toHaveLength(1);
      expect(chain[0]).toBe(leaf);
    });

    it("should handle serialization of incomplete tree", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      // Create gap
      (tree as any).sequenceIndex.delete(1);

      const serialized = tree.serialize();
      expect(serialized).toHaveLength(1);
    });
  });

  describe("Duplicate Compaction", () => {
    it("should allow multiple compactions on same session", () => {
      const parent = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", parent.entryId, "user_message", "Msg 1");
      tree.appendLeaf("session-1", parent.entryId, "user_message", "Msg 2");

      const c1 = tree.appendCompaction(
        "session-1",
        parent.entryId,
        1,
        "cursor-1",
        { summary: "First" },
        [],
        50,
      );

      const c2 = tree.appendCompaction(
        "session-1",
        parent.entryId,
        2,
        "cursor-2",
        { summary: "Second" },
        [],
        50,
      );

      expect(c1.compactedUpTo).toBe(1);
      expect(c2.compactedUpTo).toBe(2);
    });

    it("should track compaction sequence", () => {
      const parent = tree.appendParent("session-1", null);

      for (let i = 1; i <= 5; i++) {
        tree.appendCompaction(
          "session-1",
          parent.entryId,
          i,
          `cursor-${i}`,
          { summary: `Compaction ${i}` },
          [],
          50,
        );
      }

      const reconstruction = tree.reconstructSession("session-1");
      expect(reconstruction.compactions).toHaveLength(5);
    });

    it("should get last compaction correctly", () => {
      const parent = tree.appendParent("session-1", null);

      tree.appendCompaction("session-1", parent.entryId, 10, "c1", {}, [], 50);
      tree.appendCompaction("session-1", parent.entryId, 20, "c2", {}, [], 50);
      tree.appendCompaction("session-1", parent.entryId, 30, "c3", {}, [], 50);

      const last = tree.getLastCompaction("session-1");
      expect(last!.cursor).toBe("c3");
      expect(last!.compactedUpTo).toBe(30);
    });

    it("should handle compaction at same sequence point", () => {
      const parent = tree.appendParent("session-1", null);

      const c1 = tree.appendCompaction("session-1", parent.entryId, 10, "c1", {}, [], 50);
      const c2 = tree.appendCompaction("session-1", parent.entryId, 10, "c2", {}, [], 60);

      // Both allowed, but different sequence numbers
      expect(c1.seqNum).not.toBe(c2.seqNum);
      expect(c1.compactedUpTo).toBe(c2.compactedUpTo);
    });

    it("should preserve compaction metadata", () => {
      const parent = tree.appendParent("session-1", null);

      const compaction = tree.appendCompaction(
        "session-1",
        parent.entryId,
        10,
        "cursor-1",
        { summary: "Compacted content" },
        ["entry-1", "entry-2"],
        150,
        { metadata: { algorithm: "summary", version: "v1" } },
      );

      expect(compaction.compactedContent).toEqual({ summary: "Compacted content" });
      expect(compaction.originalEntries).toEqual(["entry-1", "entry-2"]);
      expect(compaction.tokensUsed).toBe(150);
      expect(compaction.metadata?.algorithm).toBe("summary");
    });
  });

  describe("Retention", () => {
    it("should filter entries before compaction point", () => {
      const parent = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", parent.entryId, "user_message", "1");
      tree.appendLeaf("session-1", parent.entryId, "user_message", "2");
      tree.appendLeaf("session-1", parent.entryId, "user_message", "3");

      tree.appendCompaction("session-1", parent.entryId, 2, "c1", {}, [], 50);

      const afterCompaction = tree.getEntriesSince(2);
      expect(afterCompaction.length).toBeGreaterThan(0);

      const beforeCompaction = tree.getEntriesUpTo(2);
      expect(beforeCompaction).toHaveLength(2);
    });

    it("should support range queries for retention", () => {
      for (let i = 1; i <= 10; i++) {
        tree.appendParent("session-1", null);
      }

      const range = tree.getEntriesUpTo(5);
      expect(range).toHaveLength(5);

      const since = tree.getEntriesSince(5);
      expect(since).toHaveLength(5);
    });

    it("should handle retention with resets", () => {
      const p1 = tree.appendParent("session-1", null);
      const l1 = tree.appendLeaf("session-1", p1.entryId, "user_message", "Keep");
      const l2 = tree.appendLeaf("session-1", p1.entryId, "user_message", "Drop");

      const reset = tree.appendReset("session-1", p1.entryId, "Retention policy", {
        preservedEntries: [l1.entryId],
      });

      expect(reset.preservedEntries).toContain(l1.entryId);
      expect(reset.preservedEntries).not.toContain(l2.entryId);
    });

    it("should track sequence for pruning decisions", () => {
      const entries: Array<{ id: string; seq: number }> = [];

      for (let i = 1; i <= 20; i++) {
        const entry = tree.appendParent("session-1", null);
        entries.push({ id: entry.entryId, seq: entry.seqNum });
      }

      // Simulate retention: keep entries after seq 10
      const retained = entries.filter((e) => e.seq > 10);
      expect(retained).toHaveLength(10);
    });

    it("should support retention across branches", () => {
      const parent = tree.appendParent("session-1", null);
      const b1 = tree.appendBranch("session-1", parent.entryId, "b1", parent.entryId);
      const b2 = tree.appendBranch("session-1", parent.entryId, "b2", parent.entryId);

      tree.appendLeaf("session-1", b1.entryId, "user_message", "B1");
      tree.appendLeaf("session-1", b2.entryId, "user_message", "B2");

      // Retention policy: keep only one branch
      const reset = tree.appendReset("session-1", parent.entryId, "Prune branches", {
        preservedEntries: [parent.entryId, b1.entryId],
      });

      expect(reset.preservedEntries).toContain(b1.entryId);
      expect(reset.preservedEntries).not.toContain(b2.entryId);
    });
  });

  describe("Integration Scenarios", () => {
    it("should handle full lifecycle: branch, compact, restore", () => {
      // Build session
      const parent = tree.appendParent("session-1", null);
      const branch = tree.appendBranch("session-1", parent.entryId, "exp", parent.entryId);
      tree.appendLeaf("session-1", branch.entryId, "user_message", "Experiment");

      // Compact
      tree.appendCompaction("session-1", parent.entryId, 2, "c1", {}, [], 100);

      // Serialize and restore
      const serialized = tree.serialize();
      const restored = SessionTree.deserialize(serialized);

      expect(restored.getCurrentSeq()).toBe(tree.getCurrentSeq());

      const reconstruction = restored.reconstructSession("session-1");
      expect(reconstruction.branches.size).toBe(1);
      expect(reconstruction.compactions).toHaveLength(1);
    });

    it("should handle concurrent modifications via sequence", () => {
      const tree1 = new SessionTree();
      const tree2 = new SessionTree();

      // Simulate two trees modifying same session
      const p1 = tree1.appendParent("session-1", null);
      const p2 = tree2.appendParent("session-1", null);

      // Sequences are independent
      expect(p1.seqNum).toBe(1);
      expect(p2.seqNum).toBe(1);
    });

    it("should maintain integrity across complex operations", () => {
      const parent = tree.appendParent("session-1", null);

      // Add various entry types
      tree.appendLeaf("session-1", parent.entryId, "user_message", "User");
      tree.appendBranch("session-1", parent.entryId, "b1", parent.entryId);
      tree.appendReset("session-1", parent.entryId, "Reset");
      tree.appendCompaction("session-1", parent.entryId, 3, "c1", {}, [], 100);

      const verification = tree.verifyContiguous();
      expect(verification.ok).toBe(true);

      const all = tree.getAllEntries();
      expect(all).toHaveLength(5);
    });
  });
});
