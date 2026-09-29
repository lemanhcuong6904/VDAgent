import { beforeEach, describe, expect, it } from "vitest";
import { SessionTree } from "../../src/session/session-tree.js";

describe("SessionTree", () => {
  let tree: SessionTree;

  beforeEach(() => {
    tree = new SessionTree();
  });

  describe("Append-Only Parent Entries", () => {
    it("should append parent entry", () => {
      const entry = tree.appendParent("session-1", null, {
        title: "Root",
      });

      expect(entry.type).toBe("parent");
      expect(entry.sessionId).toBe("session-1");
      expect(entry.seqNum).toBe(1);
      expect(entry.parentEntryId).toBeNull();
      expect(entry.title).toBe("Root");
    });

    it("should append nested parent", () => {
      const root = tree.appendParent("session-1", null);
      const child = tree.appendParent("session-1", root.entryId);

      expect(child.parentEntryId).toBe(root.entryId);
      expect(child.seqNum).toBe(2);
    });
  });

  describe("Append-Only Leaf Entries", () => {
    it("should append user message leaf", () => {
      const parent = tree.appendParent("session-1", null);
      const leaf = tree.appendLeaf(
        "session-1",
        parent.entryId,
        "user_message",
        { text: "Hello" },
        { tokensUsed: 5 },
      );

      expect(leaf.type).toBe("leaf");
      expect(leaf.contentType).toBe("user_message");
      expect(leaf.content).toEqual({ text: "Hello" });
      expect(leaf.tokensUsed).toBe(5);
      expect(leaf.seqNum).toBe(2);
    });

    it("should append assistant message leaf", () => {
      const parent = tree.appendParent("session-1", null);
      const leaf = tree.appendLeaf("session-1", parent.entryId, "assistant_message", {
        text: "Hi there",
      });

      expect(leaf.contentType).toBe("assistant_message");
    });

    it("should append tool call and result", () => {
      const parent = tree.appendParent("session-1", null);

      const toolCall = tree.appendLeaf("session-1", parent.entryId, "tool_call", {
        tool: "search",
        args: { query: "test" },
      });

      const toolResult = tree.appendLeaf("session-1", parent.entryId, "tool_result", {
        results: [],
      });

      expect(toolCall.contentType).toBe("tool_call");
      expect(toolResult.contentType).toBe("tool_result");
      expect(toolCall.seqNum).toBe(2);
      expect(toolResult.seqNum).toBe(3);
    });
  });

  describe("Branch Entries", () => {
    it("should append branch entry", () => {
      const parent = tree.appendParent("session-1", null);
      const branch = tree.appendBranch("session-1", parent.entryId, "experiment", parent.entryId);

      expect(branch.type).toBe("branch");
      expect(branch.branchName).toBe("experiment");
      expect(branch.branchedFrom).toBe(parent.entryId);
    });

    it("should track multiple branches", () => {
      const parent = tree.appendParent("session-1", null);
      const branch1 = tree.appendBranch("session-1", parent.entryId, "branch-1", parent.entryId);
      const branch2 = tree.appendBranch("session-1", parent.entryId, "branch-2", parent.entryId);

      expect(branch1.seqNum).toBe(2);
      expect(branch2.seqNum).toBe(3);
      expect(branch1.branchName).toBe("branch-1");
      expect(branch2.branchName).toBe("branch-2");
    });
  });

  describe("Reset Entries", () => {
    it("should append reset entry", () => {
      const parent = tree.appendParent("session-1", null);
      const reset = tree.appendReset("session-1", parent.entryId, "context_overflow");

      expect(reset.type).toBe("reset");
      expect(reset.reason).toBe("context_overflow");
    });

    it("should preserve specific entries on reset", () => {
      const parent = tree.appendParent("session-1", null);
      const leaf1 = tree.appendLeaf("session-1", parent.entryId, "user_message", {});
      const _leaf2 = tree.appendLeaf("session-1", parent.entryId, "assistant_message", {});

      const reset = tree.appendReset("session-1", parent.entryId, "manual", {
        preservedEntries: [leaf1.entryId],
      });

      expect(reset.preservedEntries).toEqual([leaf1.entryId]);
    });
  });

  describe("Compaction Entries", () => {
    it("should append compaction entry", () => {
      const parent = tree.appendParent("session-1", null);
      const leaf1 = tree.appendLeaf("session-1", parent.entryId, "user_message", {});
      const leaf2 = tree.appendLeaf("session-1", parent.entryId, "assistant_message", {});

      const compaction = tree.appendCompaction(
        "session-1",
        parent.entryId,
        3,
        "cursor-abc",
        { summary: "Earlier conversation..." },
        [leaf1.entryId, leaf2.entryId],
        100,
      );

      expect(compaction.type).toBe("compaction");
      expect(compaction.compactedUpTo).toBe(3);
      expect(compaction.cursor).toBe("cursor-abc");
      expect(compaction.originalEntries).toEqual([leaf1.entryId, leaf2.entryId]);
      expect(compaction.tokensUsed).toBe(100);
    });
  });

  describe("Entry Retrieval", () => {
    it("should get entry by ID", () => {
      const entry = tree.appendParent("session-1", null);
      const retrieved = tree.getEntry(entry.entryId);

      expect(retrieved).toBeDefined();
      expect(retrieved?.entryId).toBe(entry.entryId);
    });

    it("should get entry by sequence number", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      const third = tree.appendParent("session-1", null);

      const retrieved = tree.getEntryBySeq(3);

      expect(retrieved).toBeDefined();
      expect(retrieved?.entryId).toBe(third.entryId);
    });

    it("should get all entries in order", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      const entries = tree.getAllEntries();

      expect(entries).toHaveLength(3);
      expect(entries[0].seqNum).toBe(1);
      expect(entries[1].seqNum).toBe(2);
      expect(entries[2].seqNum).toBe(3);
    });

    it("should get session entries", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-2", null);
      tree.appendParent("session-1", null);

      const session1Entries = tree.getSessionEntries("session-1");

      expect(session1Entries).toHaveLength(2);
      expect(session1Entries.every((e) => e.sessionId === "session-1")).toBe(true);
    });

    it("should get children of entry", () => {
      const parent = tree.appendParent("session-1", null);
      const child1 = tree.appendParent("session-1", parent.entryId);
      const child2 = tree.appendParent("session-1", parent.entryId);

      const children = tree.getChildren(parent.entryId);

      expect(children).toHaveLength(2);
      expect(children.map((c) => c.entryId).sort()).toEqual(
        [child1.entryId, child2.entryId].sort(),
      );
    });

    it("should get parent chain", () => {
      const root = tree.appendParent("session-1", null);
      const child1 = tree.appendParent("session-1", root.entryId);
      const child2 = tree.appendParent("session-1", child1.entryId);

      const chain = tree.getParentChain(child2.entryId);

      expect(chain).toHaveLength(3);
      expect(chain[0].entryId).toBe(root.entryId);
      expect(chain[1].entryId).toBe(child1.entryId);
      expect(chain[2].entryId).toBe(child2.entryId);
    });
  });

  describe("Session Reconstruction", () => {
    it("should reconstruct session with branches", () => {
      const root = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", root.entryId, "user_message", {});

      const branch = tree.appendBranch("session-1", root.entryId, "exp-1", root.entryId);
      tree.appendLeaf("session-1", branch.entryId, "user_message", {});

      const reconstruction = tree.reconstructSession("session-1");

      expect(reconstruction.entries).toHaveLength(4);
      expect(reconstruction.branches.size).toBe(1);
      expect(reconstruction.branches.has("exp-1")).toBe(true);
    });

    it("should track compactions in reconstruction", () => {
      const root = tree.appendParent("session-1", null);
      const leaf = tree.appendLeaf("session-1", root.entryId, "user_message", {});

      tree.appendCompaction("session-1", root.entryId, 2, "cursor-1", {}, [leaf.entryId], 50);

      const reconstruction = tree.reconstructSession("session-1");

      expect(reconstruction.compactions).toHaveLength(1);
      expect(reconstruction.compactions[0].cursor).toBe("cursor-1");
    });

    it("should track resets in reconstruction", () => {
      const root = tree.appendParent("session-1", null);
      tree.appendReset("session-1", root.entryId, "overflow");

      const reconstruction = tree.reconstructSession("session-1");

      expect(reconstruction.resets).toHaveLength(1);
      expect(reconstruction.resets[0].reason).toBe("overflow");
    });
  });

  describe("Sequence Operations", () => {
    it("should get entries since sequence number", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3
      tree.appendParent("session-1", null); // seq 4

      const entries = tree.getEntriesSince(2);

      expect(entries).toHaveLength(2);
      expect(entries[0].seqNum).toBe(3);
      expect(entries[1].seqNum).toBe(4);
    });

    it("should get entries up to sequence number", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3
      tree.appendParent("session-1", null); // seq 4

      const entries = tree.getEntriesUpTo(2);

      expect(entries).toHaveLength(2);
      expect(entries[0].seqNum).toBe(1);
      expect(entries[1].seqNum).toBe(2);
    });

    it("should get last compaction", () => {
      const root = tree.appendParent("session-1", null);

      tree.appendCompaction("session-1", root.entryId, 1, "c1", {}, [], 10);
      tree.appendLeaf("session-1", root.entryId, "user_message", {});
      tree.appendCompaction("session-1", root.entryId, 3, "c2", {}, [], 20);

      const last = tree.getLastCompaction("session-1");

      expect(last).toBeDefined();
      expect(last?.cursor).toBe("c2");
      expect(last?.compactedUpTo).toBe(3);
    });

    it("should get current sequence number", () => {
      expect(tree.getCurrentSeq()).toBe(0);

      tree.appendParent("session-1", null);
      expect(tree.getCurrentSeq()).toBe(1);

      tree.appendParent("session-1", null);
      expect(tree.getCurrentSeq()).toBe(2);
    });
  });

  describe("Contiguous Verification", () => {
    it("should verify contiguous sequence", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      const result = tree.verifyContiguous();

      expect(result.ok).toBe(true);
      expect(result.gaps).toHaveLength(0);
    });

    it("should detect gaps in sequence", () => {
      tree.appendParent("session-1", null); // seq 1
      tree.appendParent("session-1", null); // seq 2
      tree.appendParent("session-1", null); // seq 3

      // Simulate gap by removing entry from internal structures
      // In production this shouldn't happen, but test detects it
      const allEntries = tree.getAllEntries();
      const _entry2 = allEntries[1];

      // This is a white-box test - accessing private Map for testing
      // In real code, gaps would come from storage corruption
      (tree as any).sequenceIndex.delete(2);

      const result = tree.verifyContiguous();

      expect(result.ok).toBe(false);
      expect(result.gaps).toContain(2);
    });
  });

  describe("Serialization and Deserialization", () => {
    it("should serialize to append-only log", () => {
      tree.appendParent("session-1", null, { title: "Root" });
      tree.appendLeaf("session-1", tree.getAllEntries()[0].entryId, "user_message", { text: "Hi" });

      const lines = tree.serialize();

      expect(lines).toHaveLength(2);
      lines.forEach((line) => {
        expect(() => JSON.parse(line)).not.toThrow();
      });
    });

    it("should deserialize from append-only log", () => {
      tree.appendParent("session-1", null, { title: "Root" });
      const parent = tree.getAllEntries()[0];
      tree.appendLeaf("session-1", parent.entryId, "user_message", { text: "Hi" });

      const lines = tree.serialize();
      const restored = SessionTree.deserialize(lines);

      const originalEntries = tree.getAllEntries();
      const restoredEntries = restored.getAllEntries();

      expect(restoredEntries).toHaveLength(originalEntries.length);
      expect(restoredEntries[0].entryId).toBe(originalEntries[0].entryId);
      expect(restoredEntries[1].entryId).toBe(originalEntries[1].entryId);
    });

    it("should maintain sequence numbers after deserialization", () => {
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);
      tree.appendParent("session-1", null);

      const lines = tree.serialize();
      const restored = SessionTree.deserialize(lines);

      expect(restored.getCurrentSeq()).toBe(3);
      expect(restored.getEntryBySeq(1)).toBeDefined();
      expect(restored.getEntryBySeq(2)).toBeDefined();
      expect(restored.getEntryBySeq(3)).toBeDefined();
    });

    it("should handle complex tree with branches and compactions", () => {
      const root = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", root.entryId, "user_message", {});
      const branch = tree.appendBranch("session-1", root.entryId, "exp", root.entryId);
      tree.appendLeaf("session-1", branch.entryId, "assistant_message", {});
      tree.appendCompaction("session-1", root.entryId, 2, "c1", {}, [], 50);
      tree.appendReset("session-1", root.entryId, "test");

      const lines = tree.serialize();
      const restored = SessionTree.deserialize(lines);

      const originalRec = tree.reconstructSession("session-1");
      const restoredRec = restored.reconstructSession("session-1");

      expect(restoredRec.entries).toHaveLength(originalRec.entries.length);
      expect(restoredRec.branches.size).toBe(originalRec.branches.size);
      expect(restoredRec.compactions).toHaveLength(originalRec.compactions.length);
      expect(restoredRec.resets).toHaveLength(originalRec.resets.length);
    });
  });

  describe("Deterministic Reconstruction", () => {
    it("should produce identical results from same log", () => {
      const root = tree.appendParent("session-1", null);
      tree.appendLeaf("session-1", root.entryId, "user_message", { text: "Test" });

      const lines = tree.serialize();

      const tree1 = SessionTree.deserialize(lines);
      const tree2 = SessionTree.deserialize(lines);

      const entries1 = tree1.getAllEntries();
      const entries2 = tree2.getAllEntries();

      expect(entries1).toHaveLength(entries2.length);
      for (let i = 0; i < entries1.length; i++) {
        expect(entries1[i].entryId).toBe(entries2[i].entryId);
        expect(entries1[i].seqNum).toBe(entries2[i].seqNum);
        expect(entries1[i].type).toBe(entries2[i].type);
      }
    });

    it("should reconstruct parent-child relationships", () => {
      const root = tree.appendParent("session-1", null);
      const child1 = tree.appendParent("session-1", root.entryId);
      const child2 = tree.appendParent("session-1", child1.entryId);

      const lines = tree.serialize();
      const restored = SessionTree.deserialize(lines);

      const chain = restored.getParentChain(child2.entryId);

      expect(chain).toHaveLength(3);
      expect(chain[0].entryId).toBe(root.entryId);
      expect(chain[1].entryId).toBe(child1.entryId);
      expect(chain[2].entryId).toBe(child2.entryId);
    });
  });
});
