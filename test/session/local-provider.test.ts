/**
 * Local Provider Tests
 * Tests for file-based memory provider with deterministic storage
 */

import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LocalProvider } from "../../src/session/memory-provider.js";

describe("LocalProvider - M8.4", () => {
  let provider: LocalProvider;
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `memory-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await fs.mkdir(testDir, { recursive: true });
    provider = new LocalProvider(testDir);
  });

  afterEach(async () => {
    try {
      await fs.rm(testDir, { recursive: true, force: true });
    } catch (_error) {
      // Ignore cleanup errors
    }
  });

  describe("Basic Persistence", () => {
    it("should persist and reload memory entries", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "test-entry",
        content: "Persisted content",
      });

      const newProvider = new LocalProvider(testDir);
      const entry = await newProvider.read("test-entry", "ws-1");

      expect(entry).not.toBeNull();
      expect(entry?.content).toBe("Persisted content");
    });

    it("should persist revision history", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "versioned",
        content: "Version 1",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "versioned",
        content: "Version 2",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "versioned",
        content: "Version 3",
      });

      const newProvider = new LocalProvider(testDir);
      const history = await newProvider.getRevisionHistory("versioned", "ws-1");

      expect(history).toHaveLength(3);
      expect(history[0].content).toBe("Version 1");
      expect(history[1].content).toBe("Version 2");
      expect(history[2].content).toBe("Version 3");
    });

    it("should maintain workspace isolation in file structure", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-1",
        content: "Workspace 1 data",
      });

      await provider.commit({
        workspaceId: "ws-2",
        scope: "entry-1",
        content: "Workspace 2 data",
      });

      const ws1Files = await fs.readdir(join(testDir, "ws-1", "entries"));
      const ws2Files = await fs.readdir(join(testDir, "ws-2", "entries"));

      expect(ws1Files).toContain("entry-1.json");
      expect(ws2Files).toContain("entry-1.json");

      const newProvider = new LocalProvider(testDir);
      const ws1Entry = await newProvider.read("entry-1", "ws-1");
      const ws2Entry = await newProvider.read("entry-1", "ws-2");

      expect(ws1Entry?.content).toBe("Workspace 1 data");
      expect(ws2Entry?.content).toBe("Workspace 2 data");
    });

    it("should handle forget with file deletion", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "to-delete",
        content: "Will be deleted",
      });

      const entryPath = join(testDir, "ws-1", "entries", "to-delete.json");
      let exists = await fs
        .access(entryPath)
        .then(() => true)
        .catch(() => false);
      expect(exists).toBe(true);

      await provider.forget("to-delete", "ws-1");

      exists = await fs
        .access(entryPath)
        .then(() => true)
        .catch(() => false);
      expect(exists).toBe(false);

      const newProvider = new LocalProvider(testDir);
      const entry = await newProvider.read("to-delete", "ws-1");
      expect(entry).toBeNull();
    });

    it("should persist all memory fields", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "full-entry",
        content: "Complete data",
        contentType: "text/plain",
        audience: "agent",
        sensitivity: "confidential",
        retention: { policy: "30-days" },
        metadata: { key: "value" },
        provenance: { source: "test", trustLevel: "trusted" },
      });

      const newProvider = new LocalProvider(testDir);
      const entry = await newProvider.read("full-entry", "ws-1");

      expect(entry?.content).toBe("Complete data");
      expect(entry?.contentType).toBe("text/plain");
      expect(entry?.audience).toBe("agent");
      expect(entry?.sensitivity).toBe("confidential");
      expect(entry?.retention?.policy).toBe("30-days");
      expect(entry?.metadata?.key).toBe("value");
      expect(entry?.provenance?.source).toBe("test");
    });
  });

  describe("Search with Persistence", () => {
    it("should search across persisted entries", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-1",
        content: "searchable content alpha",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-2",
        content: "searchable content beta",
      });

      const newProvider = new LocalProvider(testDir);
      const results = await newProvider.search("searchable", "ws-1");

      expect(results).toHaveLength(2);
    });

    it("should filter by audience after reload", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "user-data",
        content: "user content",
        audience: "user",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "agent-data",
        content: "agent content",
        audience: "agent",
      });

      const newProvider = new LocalProvider(testDir);
      const results = await newProvider.search("content", "ws-1", {
        audience: ["user"],
      });

      expect(results).toHaveLength(1);
      expect(results[0].entry.audience).toBe("user");
    });
  });

  describe("Transaction Persistence", () => {
    it("should persist transactional commits", async () => {
      await provider.commitTransaction({
        workspaceId: "ws-1",
        commits: [
          { workspaceId: "ws-1", scope: "tx-1", content: "Transaction entry 1" },
          { workspaceId: "ws-1", scope: "tx-2", content: "Transaction entry 2" },
          { workspaceId: "ws-1", scope: "tx-3", content: "Transaction entry 3" },
        ],
      });

      const newProvider = new LocalProvider(testDir);
      const entry1 = await newProvider.read("tx-1", "ws-1");
      const entry2 = await newProvider.read("tx-2", "ws-1");
      const entry3 = await newProvider.read("tx-3", "ws-1");

      expect(entry1?.content).toBe("Transaction entry 1");
      expect(entry2?.content).toBe("Transaction entry 2");
      expect(entry3?.content).toBe("Transaction entry 3");
    });

    it("should support CAS after reload", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "cas-test",
        content: "Version 1",
      });

      const newProvider = new LocalProvider(testDir);
      const result = await newProvider.commit({
        workspaceId: "ws-1",
        scope: "cas-test",
        content: "Version 2",
        expectedRevision: 1,
      });

      expect(result.ok).toBe(true);
      expect(result.entry?.revision).toBe(2);
    });
  });

  describe("Credential Persistence", () => {
    it("should persist and reload credentials", async () => {
      await provider.storeCredential("api-key", "ws-1", {
        type: "encrypted",
        keyId: "key-123",
        encryptedValue: "encrypted-data",
      });

      const newProvider = new LocalProvider(testDir);
      const credential = await newProvider.retrieveCredential("api-key", "ws-1");

      expect(credential).not.toBeNull();
      expect(credential?.keyId).toBe("key-123");
      expect(credential?.encryptedValue).toBe("encrypted-data");
    });

    it("should isolate credentials by workspace", async () => {
      await provider.storeCredential("shared-key", "ws-1", {
        type: "encrypted",
        keyId: "ws1-key",
      });

      await provider.storeCredential("shared-key", "ws-2", {
        type: "vault",
        keyId: "ws2-key",
      });

      const ws1Path = join(testDir, "ws-1", "credentials", "shared-key.json");
      const ws2Path = join(testDir, "ws-2", "credentials", "shared-key.json");

      const ws1Exists = await fs
        .access(ws1Path)
        .then(() => true)
        .catch(() => false);
      const ws2Exists = await fs
        .access(ws2Path)
        .then(() => true)
        .catch(() => false);

      expect(ws1Exists).toBe(true);
      expect(ws2Exists).toBe(true);
    });
  });

  describe("Resolver Trust Persistence", () => {
    it("should persist and reload resolver trust", async () => {
      await provider.registerResolverTrust("github-resolver", "ws-1", {
        resolverType: "github-resolver",
        trustLevel: "trusted",
        approvedBy: "admin@example.com",
      });

      const newProvider = new LocalProvider(testDir);
      const trust = await newProvider.getResolverTrust("github-resolver", "ws-1");

      expect(trust).not.toBeNull();
      expect(trust?.trustLevel).toBe("trusted");
      expect(trust?.approvedBy).toBe("admin@example.com");
    });

    it("should isolate resolver trust by workspace", async () => {
      await provider.registerResolverTrust("resolver", "ws-1", {
        resolverType: "resolver",
        trustLevel: "trusted",
      });

      await provider.registerResolverTrust("resolver", "ws-2", {
        resolverType: "resolver",
        trustLevel: "untrusted",
      });

      const newProvider = new LocalProvider(testDir);
      const ws1Trust = await newProvider.getResolverTrust("resolver", "ws-1");
      const ws2Trust = await newProvider.getResolverTrust("resolver", "ws-2");

      expect(ws1Trust?.trustLevel).toBe("trusted");
      expect(ws2Trust?.trustLevel).toBe("untrusted");
    });
  });

  describe("Approval Request Persistence", () => {
    it("should persist and reload approval requests", async () => {
      const approval = await provider.requestApproval({
        operation: "credential_access",
        resource: "api-key",
        requestedBy: "agent-1",
      });

      const newProvider = new LocalProvider(testDir);
      const retrieved = await newProvider.getApprovalRequest(approval.id);

      expect(retrieved).not.toBeNull();
      expect(retrieved?.operation).toBe("credential_access");
      expect(retrieved?.status).toBe("pending");
    });

    it("should persist approval status changes", async () => {
      const approval = await provider.requestApproval({
        operation: "export",
        resource: "workspace-data",
        requestedBy: "user-1",
      });

      await provider.processApproval(approval.id, "approved", "admin@example.com");

      const newProvider = new LocalProvider(testDir);
      const retrieved = await newProvider.getApprovalRequest(approval.id);

      expect(retrieved?.status).toBe("approved");
      expect(retrieved?.approvedBy).toBe("admin@example.com");
    });
  });

  describe("Export and Import", () => {
    it("should export persisted data", async () => {
      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-1",
        content: "Export test 1",
      });

      await provider.commit({
        workspaceId: "ws-1",
        scope: "entry-2",
        content: "Export test 2",
      });

      const exported = await provider.export("ws-1");

      expect(exported.entries).toHaveLength(2);
      expect(exported.workspaceId).toBe("ws-1");
    });

    it("should import and persist data", async () => {
      const importData = {
        version: "v1",
        exportedAt: new Date().toISOString(),
        workspaceId: "ws-source",
        entries: [
          {
            id: "imported-1",
            workspaceId: "ws-source",
            scope: "imported-1",
            content: "Imported content 1",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
          {
            id: "imported-2",
            workspaceId: "ws-source",
            scope: "imported-2",
            content: "Imported content 2",
            revision: 1,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          },
        ],
      };

      await provider.import(importData, "ws-target");

      const newProvider = new LocalProvider(testDir);
      const entry1 = await newProvider.read("imported-1", "ws-target");
      const entry2 = await newProvider.read("imported-2", "ws-target");

      expect(entry1?.content).toBe("Imported content 1");
      expect(entry2?.content).toBe("Imported content 2");
    });
  });

  describe("Concurrent Access", () => {
    it("should handle multiple provider instances", async () => {
      const provider1 = new LocalProvider(testDir);
      const provider2 = new LocalProvider(testDir);

      await provider1.commit({
        workspaceId: "ws-1",
        scope: "shared",
        content: "From provider 1",
      });

      const entry = await provider2.read("shared", "ws-1");
      expect(entry?.content).toBe("From provider 1");
    });

    it("should detect CAS conflicts across instances", async () => {
      const provider1 = new LocalProvider(testDir);
      const provider2 = new LocalProvider(testDir);

      await provider1.commit({
        workspaceId: "ws-1",
        scope: "conflict",
        content: "Initial",
      });

      await provider2.commit({
        workspaceId: "ws-1",
        scope: "conflict",
        content: "Update from provider 2",
      });

      const result = await provider1.commit({
        workspaceId: "ws-1",
        scope: "conflict",
        content: "Update from provider 1",
        expectedRevision: 1,
      });

      expect(result.ok).toBe(false);
      expect(result.conflictRevision).toBe(2);
    });
  });
});
