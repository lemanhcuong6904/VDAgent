import { beforeEach, describe, expect, it } from "vitest";
import {
  type CredentialReference,
  InMemoryProvider,
  type MemoryCommitRequest,
  type MemoryExport,
  type ResolverTrust,
} from "../../src/session/memory-provider.js";

describe("Memory Provider - M8.1", () => {
  let provider: InMemoryProvider;
  const workspaceId = "workspace-test";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  describe("Describe Operation", () => {
    it("should describe existing memory entry", async () => {
      const request: MemoryCommitRequest = {
        workspaceId,
        scope: "test-memory",
        content: "Test content",
      };

      await provider.commit(request);
      const descriptor = await provider.describe("test-memory", workspaceId);

      expect(descriptor).not.toBeNull();
      expect(descriptor!.id).toBe("test-memory");
      expect(descriptor!.scope).toBe("test-memory");
      expect(descriptor!.revision).toBe(1);
      expect(descriptor!.size).toBeGreaterThan(0);
      expect(descriptor!.createdAt).toBeDefined();
      expect(descriptor!.updatedAt).toBeDefined();
    });

    it("should return null for non-existent memory", async () => {
      const descriptor = await provider.describe("nonexistent", workspaceId);
      expect(descriptor).toBeNull();
    });

    it("should return null for forgotten memory", async () => {
      await provider.commit({
        workspaceId,
        scope: "forgotten",
        content: "To be forgotten",
      });

      await provider.forget("forgotten", workspaceId);
      const descriptor = await provider.describe("forgotten", workspaceId);

      expect(descriptor).toBeNull();
    });

    it("should return null for wrong workspace", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      const descriptor = await provider.describe("mem1", "wrong-workspace");
      expect(descriptor).toBeNull();
    });

    it("should include sensitivity in descriptor", async () => {
      await provider.commit({
        workspaceId,
        scope: "secret-mem",
        content: "Secret content",
        sensitivity: "confidential",
      });

      const descriptor = await provider.describe("secret-mem", workspaceId);
      expect(descriptor!.sensitivity).toBe("confidential");
    });
  });

  describe("Read Operation", () => {
    it("should read latest revision by default", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
        expectedRevision: 1,
      });

      const entry = await provider.read("mem1", workspaceId);
      expect(entry).not.toBeNull();
      expect(entry!.content).toBe("Version 2");
      expect(entry!.revision).toBe(2);
    });

    it("should read specific revision", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
        expectedRevision: 1,
      });

      const entry = await provider.read("mem1", workspaceId, 1);
      expect(entry).not.toBeNull();
      expect(entry!.content).toBe("Version 1");
      expect(entry!.revision).toBe(1);
    });

    it("should return null for non-existent revision", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      const entry = await provider.read("mem1", workspaceId, 999);
      expect(entry).toBeNull();
    });

    it("should return null for forgotten memory", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      await provider.forget("mem1", workspaceId);
      const entry = await provider.read("mem1", workspaceId);

      expect(entry).toBeNull();
    });

    it("should include all metadata fields", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
        contentType: "text/plain",
        sensitivity: "internal",
        metadata: { source: "test" },
        retention: { policy: "30-days" },
        provenance: { source: "api", trustLevel: "trusted" },
      });

      const entry = await provider.read("mem1", workspaceId);
      expect(entry!.contentType).toBe("text/plain");
      expect(entry!.sensitivity).toBe("internal");
      expect(entry!.metadata).toEqual({ source: "test" });
      expect(entry!.retention).toEqual({ policy: "30-days" });
      expect(entry!.provenance).toEqual({ source: "api", trustLevel: "trusted" });
    });
  });

  describe("Search Operation", () => {
    beforeEach(async () => {
      await provider.commit({
        workspaceId,
        scope: "doc1",
        content: "The quick brown fox jumps over the lazy dog",
      });

      await provider.commit({
        workspaceId,
        scope: "doc2",
        content: "Pack my box with five dozen liquor jugs",
      });

      await provider.commit({
        workspaceId,
        scope: "doc3",
        content: "How vexingly quick daft zebras jump",
      });
    });

    it("should search and return matching entries", async () => {
      const results = await provider.search("jump", workspaceId);

      expect(results.length).toBeGreaterThan(0);
      expect(results.every((r) => r.entry.content.toLowerCase().includes("jump"))).toBe(true);
    });

    it("should include scores in results", async () => {
      const results = await provider.search("jump", workspaceId);

      expect(results.every((r) => typeof r.score === "number")).toBe(true);
      expect(results.every((r) => r.score > 0)).toBe(true);
    });

    it("should include excerpts in results", async () => {
      const results = await provider.search("jump", workspaceId);

      expect(results.every((r) => r.excerpt !== undefined)).toBe(true);
    });

    it("should sort results by score descending", async () => {
      const results = await provider.search("jump", workspaceId);

      for (let i = 1; i < results.length; i++) {
        expect(results[i - 1].score).toBeGreaterThanOrEqual(results[i].score);
      }
    });

    it("should respect limit option", async () => {
      const results = await provider.search("the", workspaceId, { limit: 1 });
      expect(results.length).toBeLessThanOrEqual(1);
    });

    it("should respect offset option", async () => {
      const all = await provider.search("the", workspaceId, { limit: 10 });
      const offset = await provider.search("the", workspaceId, {
        limit: 10,
        offset: 1,
      });

      expect(offset.length).toBe(Math.max(0, all.length - 1));
    });

    it("should filter by scope", async () => {
      const results = await provider.search("", workspaceId, { scope: "doc1" });

      expect(results.every((r) => r.entry.scope === "doc1")).toBe(true);
    });

    it("should filter by sensitivity", async () => {
      await provider.commit({
        workspaceId,
        scope: "secret",
        content: "Secret document with jump",
        sensitivity: "secret",
      });

      const results = await provider.search("jump", workspaceId, {
        sensitivity: ["public", "internal"],
      });

      expect(results.every((r) => r.entry.sensitivity !== "secret")).toBe(true);
    });

    it("should handle case-insensitive search", async () => {
      const lower = await provider.search("jump", workspaceId);
      const upper = await provider.search("JUMP", workspaceId);

      expect(lower.length).toBe(upper.length);
    });

    it("should not return forgotten entries", async () => {
      await provider.forget("doc1", workspaceId);

      const results = await provider.search("fox", workspaceId);
      expect(results.every((r) => r.entry.id !== "doc1")).toBe(true);
    });
  });

  describe("Commit Operation", () => {
    it("should create new memory entry", async () => {
      const request: MemoryCommitRequest = {
        workspaceId,
        scope: "new-mem",
        content: "New content",
      };

      const result = await provider.commit(request);

      expect(result.ok).toBe(true);
      expect(result.entry).toBeDefined();
      expect(result.entry!.id).toBe("new-mem");
      expect(result.entry!.revision).toBe(1);
      expect(result.entry!.content).toBe("New content");
    });

    it("should update existing memory entry", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      const result = await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
      });

      expect(result.ok).toBe(true);
      expect(result.entry!.revision).toBe(2);
      expect(result.entry!.content).toBe("Version 2");
    });

    it("should support CAS with expected revision", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      const result = await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
        expectedRevision: 1,
      });

      expect(result.ok).toBe(true);
      expect(result.entry!.revision).toBe(2);
    });

    it("should fail CAS with wrong expected revision", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
      });

      const result = await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 3",
        expectedRevision: 1,
      });

      expect(result.ok).toBe(false);
      expect(result.conflictRevision).toBe(2);
      expect(result.reason).toContain("CAS conflict");
    });

    it("should fail CAS when entry does not exist", async () => {
      const result = await provider.commit({
        workspaceId,
        scope: "nonexistent",
        content: "Content",
        expectedRevision: 1,
      });

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("does not exist");
    });

    it("should preserve createdAt on updates", async () => {
      const first = await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      // Small delay to ensure different timestamps
      await new Promise((resolve) => setTimeout(resolve, 10));

      const second = await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
      });

      expect(second.entry!.createdAt).toBe(first.entry!.createdAt);
      expect(second.entry!.updatedAt).not.toBe(first.entry!.updatedAt);
    });

    it("should allow re-creating forgotten memory", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Original",
      });

      await provider.forget("mem1", workspaceId);

      const result = await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Recreated",
      });

      expect(result.ok).toBe(true);
      expect(result.entry!.revision).toBe(2);
    });
  });

  describe("Forget Operation", () => {
    it("should mark memory as forgotten", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      const result = await provider.forget("mem1", workspaceId);
      expect(result).toBe(true);

      const entry = await provider.read("mem1", workspaceId);
      expect(entry).toBeNull();
    });

    it("should return false for non-existent memory", async () => {
      const result = await provider.forget("nonexistent", workspaceId);
      expect(result).toBe(false);
    });

    it("should return false for wrong workspace", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      const result = await provider.forget("mem1", "wrong-workspace");
      expect(result).toBe(false);
    });

    it("should accept optional reason parameter", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      const result = await provider.forget("mem1", workspaceId, "User requested deletion");
      expect(result).toBe(true);
    });
  });

  describe("Export Operation", () => {
    beforeEach(async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content 1",
      });

      await provider.commit({
        workspaceId,
        scope: "mem2",
        content: "Content 2",
      });

      await provider.commit({
        workspaceId: "other-workspace",
        scope: "mem3",
        content: "Content 3",
      });
    });

    it("should export all entries for workspace", async () => {
      const exported = await provider.export(workspaceId);

      expect(exported.version).toBe("v1");
      expect(exported.workspaceId).toBe(workspaceId);
      expect(exported.exportedAt).toBeDefined();
      expect(exported.entries).toHaveLength(2);
      expect(exported.entries.every((e) => e.workspaceId === workspaceId)).toBe(true);
    });

    it("should filter by scope", async () => {
      const exported = await provider.export(workspaceId, "mem1");

      expect(exported.entries).toHaveLength(1);
      expect(exported.entries[0].scope).toBe("mem1");
    });

    it("should exclude forgotten entries", async () => {
      await provider.forget("mem1", workspaceId);

      const exported = await provider.export(workspaceId);
      expect(exported.entries.every((e) => e.id !== "mem1")).toBe(true);
    });

    it("should export latest revision only", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Updated content",
      });

      const exported = await provider.export(workspaceId, "mem1");

      expect(exported.entries).toHaveLength(1);
      expect(exported.entries[0].revision).toBe(2);
      expect(exported.entries[0].content).toBe("Updated content");
    });
  });

  describe("Import Operation", () => {
    it("should import entries", async () => {
      const data: MemoryExport = {
        version: "v1",
        exportedAt: new Date().toISOString(),
        workspaceId: "source-workspace",
        entries: [
          {
            id: "mem1",
            workspaceId: "source-workspace",
            scope: "mem1",
            content: "Content 1",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
          {
            id: "mem2",
            workspaceId: "source-workspace",
            scope: "mem2",
            content: "Content 2",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
        ],
      };

      const result = await provider.import(data, workspaceId);

      expect(result.ok).toBe(true);
      expect(result.imported).toBe(2);
      expect(result.skipped).toBe(0);
      expect(result.failed).toBe(0);

      const entry1 = await provider.read("mem1", workspaceId);
      const entry2 = await provider.read("mem2", workspaceId);

      expect(entry1).not.toBeNull();
      expect(entry2).not.toBeNull();
      expect(entry1!.content).toBe("Content 1");
      expect(entry2!.content).toBe("Content 2");
    });

    it("should override workspace ID on import", async () => {
      const data: MemoryExport = {
        version: "v1",
        exportedAt: new Date().toISOString(),
        workspaceId: "source-workspace",
        entries: [
          {
            id: "mem1",
            workspaceId: "source-workspace",
            scope: "mem1",
            content: "Content",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
        ],
      };

      await provider.import(data, "target-workspace");

      const entry = await provider.read("mem1", "target-workspace");
      expect(entry).not.toBeNull();
      expect(entry!.workspaceId).toBe("target-workspace");
    });

    it("should report import statistics", async () => {
      // Pre-populate one entry
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Existing",
      });

      const data: MemoryExport = {
        version: "v1",
        exportedAt: new Date().toISOString(),
        workspaceId,
        entries: [
          {
            id: "mem1",
            workspaceId,
            scope: "mem1",
            content: "Updated",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
          {
            id: "mem2",
            workspaceId,
            scope: "mem2",
            content: "New",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
        ],
      };

      const result = await provider.import(data, workspaceId);

      expect(result.imported).toBeGreaterThan(0);
      expect(result.ok).toBe(true);
    });

    it("should preserve metadata on import", async () => {
      const data: MemoryExport = {
        version: "v1",
        exportedAt: new Date().toISOString(),
        workspaceId,
        entries: [
          {
            id: "mem1",
            workspaceId,
            scope: "mem1",
            content: "Content",
            contentType: "application/json",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            sensitivity: "confidential",
            metadata: { source: "export" },
          },
        ],
      };

      await provider.import(data, workspaceId);

      const entry = await provider.read("mem1", workspaceId);
      expect(entry!.contentType).toBe("application/json");
      expect(entry!.sensitivity).toBe("confidential");
      expect(entry!.metadata).toEqual({ source: "export" });
    });
  });

  describe("List Operation", () => {
    beforeEach(async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content 1",
      });

      await provider.commit({
        workspaceId,
        scope: "mem2",
        content: "Content 2",
        sensitivity: "internal",
      });

      await provider.commit({
        workspaceId: "other-workspace",
        scope: "mem3",
        content: "Content 3",
      });
    });

    it("should list all entries for workspace", async () => {
      const descriptors = await provider.list(workspaceId);

      expect(descriptors).toHaveLength(2);
      expect(descriptors.every((d) => ["mem1", "mem2"].includes(d.id))).toBe(true);
    });

    it("should filter by scope", async () => {
      const descriptors = await provider.list(workspaceId, { scope: "mem1" });

      expect(descriptors).toHaveLength(1);
      expect(descriptors[0].id).toBe("mem1");
    });

    it("should exclude forgotten entries", async () => {
      await provider.forget("mem1", workspaceId);

      const descriptors = await provider.list(workspaceId);
      expect(descriptors.every((d) => d.id !== "mem1")).toBe(true);
    });

    it("should return descriptors not full entries", async () => {
      const descriptors = await provider.list(workspaceId);

      for (const descriptor of descriptors) {
        expect(descriptor.id).toBeDefined();
        expect(descriptor.scope).toBeDefined();
        expect(descriptor.revision).toBeDefined();
        expect(descriptor.size).toBeDefined();
        expect(descriptor.createdAt).toBeDefined();
        expect(descriptor.updatedAt).toBeDefined();
        // Should not have content
        expect((descriptor as any).content).toBeUndefined();
      }
    });
  });

  describe("Revision History", () => {
    it("should return all revisions", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
      });

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
      });

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 3",
      });

      const history = await provider.getRevisionHistory("mem1", workspaceId);

      expect(history).toHaveLength(3);
      expect(history[0].revision).toBe(1);
      expect(history[1].revision).toBe(2);
      expect(history[2].revision).toBe(3);
    });

    it("should return empty array for non-existent memory", async () => {
      const history = await provider.getRevisionHistory("nonexistent", workspaceId);
      expect(history).toHaveLength(0);
    });

    it("should return empty array for forgotten memory", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      await provider.forget("mem1", workspaceId);

      const history = await provider.getRevisionHistory("mem1", workspaceId);
      expect(history).toHaveLength(0);
    });

    it("should include full entry data in history", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 1",
        metadata: { version: 1 },
      });

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Version 2",
        metadata: { version: 2 },
      });

      const history = await provider.getRevisionHistory("mem1", workspaceId);

      expect(history[0].content).toBe("Version 1");
      expect(history[0].metadata).toEqual({ version: 1 });
      expect(history[1].content).toBe("Version 2");
      expect(history[1].metadata).toEqual({ version: 2 });
    });
  });

  describe("Test Utilities", () => {
    it("should clear all data", async () => {
      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      await provider.commit({
        workspaceId,
        scope: "mem2",
        content: "Content",
      });

      expect(provider.size()).toBe(2);

      provider.clear();

      expect(provider.size()).toBe(0);
      const entry = await provider.read("mem1", workspaceId);
      expect(entry).toBeNull();
    });

    it("should track size correctly", async () => {
      expect(provider.size()).toBe(0);

      await provider.commit({
        workspaceId,
        scope: "mem1",
        content: "Content",
      });

      expect(provider.size()).toBe(1);

      await provider.commit({
        workspaceId,
        scope: "mem2",
        content: "Content",
      });

      expect(provider.size()).toBe(2);

      await provider.forget("mem1", workspaceId);

      expect(provider.size()).toBe(1);
    });
  });

  describe("Integration Scenarios", () => {
    it("should handle full lifecycle", async () => {
      // Create
      const create = await provider.commit({
        workspaceId,
        scope: "doc1",
        content: "Initial content",
        sensitivity: "internal",
      });

      expect(create.ok).toBe(true);

      // Read
      const read1 = await provider.read("doc1", workspaceId);
      expect(read1!.content).toBe("Initial content");

      // Update
      const update = await provider.commit({
        workspaceId,
        scope: "doc1",
        content: "Updated content",
        expectedRevision: 1,
      });

      expect(update.ok).toBe(true);

      // Search
      const search = await provider.search("Updated", workspaceId);
      expect(search.some((r) => r.entry.id === "doc1")).toBe(true);

      // Export
      const exported = await provider.export(workspaceId);
      expect(exported.entries.some((e) => e.id === "doc1")).toBe(true);

      // Forget
      const forget = await provider.forget("doc1", workspaceId);
      expect(forget).toBe(true);

      // Verify forgotten
      const read2 = await provider.read("doc1", workspaceId);
      expect(read2).toBeNull();
    });

    it("should maintain isolation between workspaces", async () => {
      await provider.commit({
        workspaceId: "workspace-1",
        scope: "mem1",
        content: "Workspace 1 content",
      });

      await provider.commit({
        workspaceId: "workspace-2",
        scope: "mem1",
        content: "Workspace 2 content",
      });

      const entry1 = await provider.read("mem1", "workspace-1");
      const entry2 = await provider.read("mem1", "workspace-2");

      expect(entry1!.content).toBe("Workspace 1 content");
      expect(entry2!.content).toBe("Workspace 2 content");

      const export1 = await provider.export("workspace-1");
      const export2 = await provider.export("workspace-2");

      expect(export1.entries).toHaveLength(1);
      expect(export2.entries).toHaveLength(1);
    });

    it("should handle concurrent updates with CAS", async () => {
      await provider.commit({
        workspaceId,
        scope: "doc1",
        content: "Initial",
      });

      // Simulate two concurrent updates
      const update1 = provider.commit({
        workspaceId,
        scope: "doc1",
        content: "Update 1",
        expectedRevision: 1,
      });

      const update2 = provider.commit({
        workspaceId,
        scope: "doc1",
        content: "Update 2",
        expectedRevision: 1,
      });

      const [result1, result2] = await Promise.all([update1, update2]);

      // One should succeed, one should fail
      const succeeded = [result1, result2].filter((r) => r.ok);
      const failed = [result1, result2].filter((r) => !r.ok);

      expect(succeeded).toHaveLength(1);
      expect(failed).toHaveLength(1);
      expect(failed[0].conflictRevision).toBe(2);
    });
  });
  describe("M8.2: Audience Control", () => {
    it("should set and retrieve audience field", async () => {
      const result = await provider.commit({
        workspaceId: "ws-1",
        scope: "scoped-memory",
        content: "Agent-specific data",
        audience: "agent",
      });

      expect(result.ok).toBe(true);
      expect(result.entry?.audience).toBe("agent");

      const read = await provider.read("scoped-memory", "ws-1");
      expect(read?.audience).toBe("agent");
    });

    it("should default to public audience when not specified", async () => {
      const result = await provider.commit({
        workspaceId: "ws-1",
        scope: "public-memory",
        content: "Public data",
      });

      expect(result.ok).toBe(true);
      expect(result.entry?.audience).toBeUndefined();
    });

    it("should filter by audience in search", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "user-data",
        content: "User-facing content data",
        audience: "user",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "agent-data",
        content: "Agent internal data",
        audience: "agent",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "system-data",
        content: "System config data",
        audience: "system",
      });

      const userResults = await provider.search("data", "ws-1", {
        audience: ["user"],
      });

      expect(userResults).toHaveLength(1);
      expect(userResults[0].entry.audience).toBe("user");

      const agentResults = await provider.search("data", "ws-1", {
        audience: ["agent"],
      });

      expect(agentResults).toHaveLength(1);
      expect(agentResults[0].entry.audience).toBe("agent");
    });

    it("should filter by multiple audiences", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "user-data",
        content: "User content",
        audience: "user",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "agent-data",
        content: "Agent content",
        audience: "agent",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "system-data",
        content: "System content",
        audience: "system",
      });

      const results = await provider.search("content", "ws-1", {
        audience: ["user", "agent"],
      });

      expect(results).toHaveLength(2);
      expect(results.map((r) => r.entry.audience).sort()).toEqual(["agent", "user"]);
    });

    it("should include public entries when filtering by audience", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "public-data",
        content: "Public content",
        audience: "public",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "user-data",
        content: "User content",
        audience: "user",
      });

      const results = await provider.search("content", "ws-1", {
        audience: ["public", "user"],
      });

      expect(results).toHaveLength(2);
    });

    it("should preserve audience through revision updates", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "tracked",
        content: "Version 1",
        audience: "agent",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "tracked",
        content: "Version 2",
        audience: "agent",
        expectedRevision: 1,
      });

      const history = await provider.getRevisionHistory("tracked", "ws-1");
      expect(history).toHaveLength(2);
      expect(history[0].audience).toBe("agent");
      expect(history[1].audience).toBe("agent");
    });
  });

  describe("M8.2: Transactional Commits", () => {
    it("should commit multiple entries atomically", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          { workspaceId: "ws-1", scope: "entry-1", content: "Content 1" },
          { workspaceId: "ws-1", scope: "entry-2", content: "Content 2" },
          { workspaceId: "ws-1", scope: "entry-3", content: "Content 3" },
        ],
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.entries).toHaveLength(3);
      expect(txResult.transactionId).toBeDefined();

      const entry1 = await provider.read("entry-1", "ws-1");
      const entry2 = await provider.read("entry-2", "ws-1");
      const entry3 = await provider.read("entry-3", "ws-1");

      expect(entry1?.content).toBe("Content 1");
      expect(entry2?.content).toBe("Content 2");
      expect(entry3?.content).toBe("Content 3");
    });

    it("should abort transaction on CAS conflict", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "existing",
        content: "Version 1",
      });

      // Simulate concurrent update
      await provider.commit({
        workspaceId: "ws-1",
        scope: "existing",
        content: "Version 2",
      });

      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "existing",
            content: "Transaction update",
            expectedRevision: 1, // Stale revision
          },
          {
            workspaceId: "ws-1",
            scope: "new-entry",
            content: "Should not be created",
          },
        ],
      });

      expect(txResult.ok).toBe(false);
      expect(txResult.reason).toContain("CAS conflict");

      // Verify new-entry was not created
      const newEntry = await provider.read("new-entry", "ws-1");
      expect(newEntry).toBeNull();
    });

    it("should validate all CAS constraints before committing", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-1",
        content: "V1",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-2",
        content: "V1",
      });

      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "entry-1",
            content: "V2",
            expectedRevision: 1,
          },
          {
            workspaceId: "ws-1",
            scope: "entry-2",
            content: "V2",
            expectedRevision: 999, // Wrong revision
          },
        ],
      });

      expect(txResult.ok).toBe(false);

      // Verify entry-1 was not updated
      const entry1 = await provider.read("entry-1", "ws-1");
      expect(entry1?.content).toBe("V1");
      expect(entry1?.revision).toBe(1);
    });

    it("should support mixed create and update in transaction", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "existing",
        content: "Original",
      });

      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "existing",
            content: "Updated",
            expectedRevision: 1,
          },
          {
            workspaceId: "ws-1",
            scope: "new-1",
            content: "New entry 1",
          },
          {
            workspaceId: "ws-1",
            scope: "new-2",
            content: "New entry 2",
          },
        ],
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.entries).toHaveLength(3);

      const existing = await provider.read("existing", "ws-1");
      expect(existing?.content).toBe("Updated");
      expect(existing?.revision).toBe(2);
    });

    it("should include transaction metadata", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [{ workspaceId: "ws-1", scope: "e1", content: "C1" }],
        transactionId: "custom-tx-123",
        metadata: { reason: "batch-update", userId: "user-42" },
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.transactionId).toBe("custom-tx-123");
    });

    it("should generate transaction ID if not provided", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [{ workspaceId: "ws-1", scope: "e1", content: "C1" }],
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.transactionId).toBeDefined();
      expect(txResult.transactionId).toMatch(/^txn-/);
    });

    it("should handle transaction with all audience types", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "user-mem",
            content: "User data",
            audience: "user",
          },
          {
            workspaceId: "ws-1",
            scope: "agent-mem",
            content: "Agent data",
            audience: "agent",
          },
          {
            workspaceId: "ws-1",
            scope: "system-mem",
            content: "System data",
            audience: "system",
          },
        ],
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.entries).toHaveLength(3);

      const userMem = await provider.read("user-mem", "ws-1");
      expect(userMem?.audience).toBe("user");
    });

    it("should return partial results for successful commits", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          { workspaceId: "ws-1", scope: "e1", content: "C1" },
          { workspaceId: "ws-1", scope: "e2", content: "C2" },
          { workspaceId: "ws-1", scope: "e3", content: "C3" },
        ],
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.partialResults).toHaveLength(3);
      expect(txResult.partialResults?.every((r) => r.ok)).toBe(true);
    });

    it("should handle empty transaction", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [],
      });

      expect(txResult.ok).toBe(true);
      expect(txResult.entries).toHaveLength(0);
    });

    it("should preserve sensitivity and retention in transaction", async () => {
      const txResult = await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "secure-data",
            content: "Confidential information",
            sensitivity: "confidential",
            retention: { policy: "30-days" },
          },
        ],
      });

      expect(txResult.ok).toBe(true);

      const entry = await provider.read("secure-data", "ws-1");
      expect(entry?.sensitivity).toBe("confidential");
      expect(entry?.retention?.policy).toBe("30-days");
    });
  });

  describe("M8.2: Integration - Audience + Transactions", () => {
    it("should filter transactional entries by audience", async () => {
      await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "batch-user-1",
            content: "User batch content 1",
            audience: "user",
          },
          {
            workspaceId: "ws-1",
            scope: "batch-user-2",
            content: "User batch content 2",
            audience: "user",
          },
          {
            workspaceId: "ws-1",
            scope: "batch-agent-1",
            content: "Agent batch content",
            audience: "agent",
          },
        ],
      });

      const userResults = await provider.search("batch", "ws-1", {
        audience: ["user"],
      });

      expect(userResults).toHaveLength(2);
      expect(userResults.every((r) => r.entry.audience === "user")).toBe(true);
    });

    it("should handle concurrent transactions with audience isolation", async () => {
      const tx1 = provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "shared-1",
            content: "User view",
            audience: "user",
          },
        ],
      });

      const tx2 = provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          {
            workspaceId: "ws-1",
            scope: "shared-2",
            content: "Agent view",
            audience: "agent",
          },
        ],
      });

      const [result1, result2] = await Promise.all([tx1, tx2]);

      expect(result1.ok).toBe(true);
      expect(result2.ok).toBe(true);

      const userEntries = await provider.search("view", "ws-1", {
        audience: ["user"],
      });
      const agentEntries = await provider.search("view", "ws-1", {
        audience: ["agent"],
      });

      expect(userEntries).toHaveLength(1);
      expect(agentEntries).toHaveLength(1);
    });
  });

  describe("M8.3: Credential Storage", () => {
    it("should store and retrieve encrypted credential reference", async () => {
      const credential: CredentialReference = {
        type: "encrypted",
        keyId: "key-123",
        encryptedValue: "encrypted-data-here",
        metadata: { purpose: "api-access" },
      };

      const storeResult = await provider.storeCredential("api-key", "ws-1", credential);
      expect(storeResult.ok).toBe(true);

      const retrieved = await provider.retrieveCredential("api-key", "ws-1");
      expect(retrieved).toEqual(credential);
    });

    it("should support different credential types", async () => {
      await provider.storeCredential("vault-cred", "ws-1", {
        type: "vault",
        keyId: "vault-key-456",
      });

      await provider.storeCredential("keyring-cred", "ws-1", {
        type: "keyring",
        keyId: "keyring-789",
      });

      const vaultCred = await provider.retrieveCredential("vault-cred", "ws-1");
      const keyringCred = await provider.retrieveCredential("keyring-cred", "ws-1");

      expect(vaultCred?.type).toBe("vault");
      expect(keyringCred?.type).toBe("keyring");
    });

    it("should return null for non-existent credential", async () => {
      const result = await provider.retrieveCredential("non-existent", "ws-1");
      expect(result).toBeNull();
    });

    it("should isolate credentials by workspace", async () => {
      const credential: CredentialReference = {
        type: "encrypted",
        keyId: "shared-key",
        encryptedValue: "ws1-data",
      };

      await provider.storeCredential("shared-scope", "ws-1", credential);
      await provider.storeCredential("shared-scope", "ws-2", {
        type: "encrypted",
        keyId: "shared-key",
        encryptedValue: "ws2-data",
      });

      const ws1Cred = await provider.retrieveCredential("shared-scope", "ws-1");
      const ws2Cred = await provider.retrieveCredential("shared-scope", "ws-2");

      expect(ws1Cred?.encryptedValue).toBe("ws1-data");
      expect(ws2Cred?.encryptedValue).toBe("ws2-data");
    });

    it("should overwrite existing credential on re-store", async () => {
      await provider.storeCredential("updatable", "ws-1", {
        type: "encrypted",
        keyId: "old-key",
        encryptedValue: "old-value",
      });

      await provider.storeCredential("updatable", "ws-1", {
        type: "encrypted",
        keyId: "new-key",
        encryptedValue: "new-value",
      });

      const retrieved = await provider.retrieveCredential("updatable", "ws-1");
      expect(retrieved?.keyId).toBe("new-key");
      expect(retrieved?.encryptedValue).toBe("new-value");
    });
  });

  describe("M8.3: Resolver Trust Classification", () => {
    it("should register and retrieve resolver trust", async () => {
      const trust: ResolverTrust = {
        resolverType: "github-resolver",
        trustLevel: "trusted",
        approvedBy: "admin@example.com",
        approvedAt: "2026-09-27T10:00:00Z",
      };

      const result = await provider.registerResolverTrust("github-resolver", "ws-1", trust);
      expect(result.ok).toBe(true);

      const retrieved = await provider.getResolverTrust("github-resolver", "ws-1");
      expect(retrieved).toEqual(trust);
    });

    it("should support all trust levels", async () => {
      await provider.registerResolverTrust("trusted-resolver", "ws-1", {
        resolverType: "trusted-resolver",
        trustLevel: "trusted",
      });

      await provider.registerResolverTrust("untrusted-resolver", "ws-1", {
        resolverType: "untrusted-resolver",
        trustLevel: "untrusted",
      });

      await provider.registerResolverTrust("unknown-resolver", "ws-1", {
        resolverType: "unknown-resolver",
        trustLevel: "unknown",
      });

      const trusted = await provider.getResolverTrust("trusted-resolver", "ws-1");
      const untrusted = await provider.getResolverTrust("untrusted-resolver", "ws-1");
      const unknown = await provider.getResolverTrust("unknown-resolver", "ws-1");

      expect(trusted?.trustLevel).toBe("trusted");
      expect(untrusted?.trustLevel).toBe("untrusted");
      expect(unknown?.trustLevel).toBe("unknown");
    });

    it("should return null for non-existent resolver trust", async () => {
      const result = await provider.getResolverTrust("non-existent", "ws-1");
      expect(result).toBeNull();
    });

    it("should isolate resolver trust by workspace", async () => {
      await provider.registerResolverTrust("shared-resolver", "ws-1", {
        resolverType: "shared-resolver",
        trustLevel: "trusted",
        approvedBy: "ws1-admin",
      });

      await provider.registerResolverTrust("shared-resolver", "ws-2", {
        resolverType: "shared-resolver",
        trustLevel: "untrusted",
        approvedBy: "ws2-admin",
      });

      const ws1Trust = await provider.getResolverTrust("shared-resolver", "ws-1");
      const ws2Trust = await provider.getResolverTrust("shared-resolver", "ws-2");

      expect(ws1Trust?.trustLevel).toBe("trusted");
      expect(ws1Trust?.approvedBy).toBe("ws1-admin");
      expect(ws2Trust?.trustLevel).toBe("untrusted");
      expect(ws2Trust?.approvedBy).toBe("ws2-admin");
    });

    it("should include restrictions in resolver trust", async () => {
      await provider.registerResolverTrust("restricted-resolver", "ws-1", {
        resolverType: "restricted-resolver",
        trustLevel: "trusted",
        restrictions: ["read-only", "rate-limited"],
      });

      const retrieved = await provider.getResolverTrust("restricted-resolver", "ws-1");
      expect(retrieved?.restrictions).toEqual(["read-only", "rate-limited"]);
    });
  });

  describe("M8.3: Approval Request Workflow", () => {
    it("should create approval request with pending status", async () => {
      const approval = await provider.requestApproval({
        operation: "credential_access",
        resource: "api-key-prod",
        requestedBy: "agent-42",
      });

      expect(approval.id).toBeDefined();
      expect(approval.id).toMatch(/^approval-/);
      expect(approval.status).toBe("pending");
      expect(approval.operation).toBe("credential_access");
      expect(approval.resource).toBe("api-key-prod");
      expect(approval.requestedBy).toBe("agent-42");
      expect(approval.requestedAt).toBeDefined();
    });

    it("should approve pending approval request", async () => {
      const approval = await provider.requestApproval({
        operation: "export",
        resource: "workspace-data",
        requestedBy: "user-123",
      });

      const processResult = await provider.processApproval(
        approval.id,
        "approved",
        "admin@example.com",
        "Export authorized for backup",
      );

      expect(processResult.ok).toBe(true);

      const retrieved = await provider.getApprovalRequest(approval.id);
      expect(retrieved?.status).toBe("approved");
      expect(retrieved?.approvedBy).toBe("admin@example.com");
      expect(retrieved?.approvedAt).toBeDefined();
      expect(retrieved?.reason).toBe("Export authorized for backup");
    });

    it("should deny pending approval request", async () => {
      const approval = await provider.requestApproval({
        operation: "delete",
        resource: "memory-entry-456",
        requestedBy: "agent-99",
      });

      const processResult = await provider.processApproval(
        approval.id,
        "denied",
        "security@example.com",
        "Insufficient privileges",
      );

      expect(processResult.ok).toBe(true);

      const retrieved = await provider.getApprovalRequest(approval.id);
      expect(retrieved?.status).toBe("denied");
      expect(retrieved?.approvedBy).toBe("security@example.com");
      expect(retrieved?.reason).toBe("Insufficient privileges");
    });

    it("should return error for non-existent approval request", async () => {
      const result = await provider.processApproval(
        "non-existent-id",
        "approved",
        "admin@example.com",
      );

      expect(result.ok).toBe(false);
      expect(result.reason).toBe("Approval request not found");
    });

    it("should prevent processing already approved request", async () => {
      const approval = await provider.requestApproval({
        operation: "resolver_use",
        resource: "untrusted-resolver",
        requestedBy: "agent-1",
      });

      await provider.processApproval(approval.id, "approved", "admin@example.com");

      const secondProcess = await provider.processApproval(
        approval.id,
        "denied",
        "other-admin@example.com",
      );

      expect(secondProcess.ok).toBe(false);
      expect(secondProcess.reason).toContain("already approved");
    });

    it("should prevent processing already denied request", async () => {
      const approval = await provider.requestApproval({
        operation: "credential_access",
        resource: "secret-key",
        requestedBy: "agent-2",
      });

      await provider.processApproval(approval.id, "denied", "admin@example.com");

      const secondProcess = await provider.processApproval(
        approval.id,
        "approved",
        "other-admin@example.com",
      );

      expect(secondProcess.ok).toBe(false);
      expect(secondProcess.reason).toContain("already denied");
    });

    it("should support all operation types", async () => {
      const credentialApproval = await provider.requestApproval({
        operation: "credential_access",
        resource: "key-1",
        requestedBy: "agent-1",
      });

      const resolverApproval = await provider.requestApproval({
        operation: "resolver_use",
        resource: "resolver-1",
        requestedBy: "agent-2",
      });

      const exportApproval = await provider.requestApproval({
        operation: "export",
        resource: "ws-data",
        requestedBy: "user-3",
      });

      const deleteApproval = await provider.requestApproval({
        operation: "delete",
        resource: "entry-4",
        requestedBy: "admin-4",
      });

      expect(credentialApproval.operation).toBe("credential_access");
      expect(resolverApproval.operation).toBe("resolver_use");
      expect(exportApproval.operation).toBe("export");
      expect(deleteApproval.operation).toBe("delete");
    });

    it("should return null for non-existent approval request retrieval", async () => {
      const result = await provider.getApprovalRequest("non-existent-approval-id");
      expect(result).toBeNull();
    });

    it("should process approval without reason", async () => {
      const approval = await provider.requestApproval({
        operation: "export",
        resource: "minimal-data",
        requestedBy: "user-5",
      });

      const processResult = await provider.processApproval(
        approval.id,
        "approved",
        "admin@example.com",
      );

      expect(processResult.ok).toBe(true);

      const retrieved = await provider.getApprovalRequest(approval.id);
      expect(retrieved?.status).toBe("approved");
      expect(retrieved?.reason).toBeUndefined();
    });
  });

  describe("M8.3: Integration Tests", () => {
    it("should combine credentials with memory entries", async () => {
      // Store credential
      await provider.storeCredential("github-token", "ws-1", {
        type: "encrypted",
        keyId: "gh-key-789",
        encryptedValue: "encrypted-token-data",
      });

      // Store memory entry referencing the credential
      await provider.commit({
        workspaceId: "ws-1",
        scope: "github-integration",
        content: "GitHub API integration configured",
        metadata: {
          credentialScope: "github-token",
        },
      });

      const credential = await provider.retrieveCredential("github-token", "ws-1");
      const memory = await provider.read("github-integration", "ws-1");

      expect(credential).toBeDefined();
      expect(memory?.metadata?.credentialScope).toBe("github-token");
    });

    it("should require approval before using untrusted resolver", async () => {
      // Register untrusted resolver
      await provider.registerResolverTrust("experimental-resolver", "ws-1", {
        resolverType: "experimental-resolver",
        trustLevel: "untrusted",
      });

      // Request approval
      const approval = await provider.requestApproval({
        operation: "resolver_use",
        resource: "experimental-resolver",
        requestedBy: "agent-experimental",
      });

      expect(approval.status).toBe("pending");

      const trust = await provider.getResolverTrust("experimental-resolver", "ws-1");
      expect(trust?.trustLevel).toBe("untrusted");

      // Approve
      await provider.processApproval(approval.id, "approved", "deployment-owner@example.com");

      const approvedRequest = await provider.getApprovalRequest(approval.id);
      expect(approvedRequest?.status).toBe("approved");
    });

    it("should isolate all M8.3 features by workspace", async () => {
      // Workspace 1
      await provider.storeCredential("shared-key", "ws-1", {
        type: "encrypted",
        keyId: "ws1-key",
      });
      await provider.registerResolverTrust("shared-resolver", "ws-1", {
        resolverType: "shared-resolver",
        trustLevel: "trusted",
      });

      // Workspace 2
      await provider.storeCredential("shared-key", "ws-2", {
        type: "vault",
        keyId: "ws2-key",
      });
      await provider.registerResolverTrust("shared-resolver", "ws-2", {
        resolverType: "shared-resolver",
        trustLevel: "unknown",
      });

      const ws1Cred = await provider.retrieveCredential("shared-key", "ws-1");
      const ws2Cred = await provider.retrieveCredential("shared-key", "ws-2");
      const ws1Trust = await provider.getResolverTrust("shared-resolver", "ws-1");
      const ws2Trust = await provider.getResolverTrust("shared-resolver", "ws-2");

      expect(ws1Cred?.type).toBe("encrypted");
      expect(ws2Cred?.type).toBe("vault");
      expect(ws1Trust?.trustLevel).toBe("trusted");
      expect(ws2Trust?.trustLevel).toBe("unknown");
    });
  });
});
