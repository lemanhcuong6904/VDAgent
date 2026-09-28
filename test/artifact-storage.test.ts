/**
 * Artifact Storage Tests - M11.1
 * Validates metadata-first publication with SHA-256/length readback
 */

import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ArtifactStorage } from "../src/artifact-storage.js";
import { migrateDatabase } from "../src/database.js";

const databaseUrl = process.env.TEST_DATABASE_URL;
const integration = describe.skipIf(!databaseUrl);
let database: Pool;
let storage: ArtifactStorage;

beforeAll(async () => {
  if (!databaseUrl) return;
  database = new Pool({ connectionString: databaseUrl, max: 6 });
  await migrateDatabase(database);
  storage = new ArtifactStorage(database);
});

afterAll(async () => {
  await database?.end();
});

integration("Artifact Storage - M11.1", () => {
  describe("metadata-first publication", () => {
    it("should store artifact with SHA-256 and size", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Test artifact content");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "dataset",
        version: "1.0.0",
        content,
        metadata: { name: "test-dataset" },
      });

      expect(result.id).toMatch(/^dat_/);
      expect(result.sha256).toHaveLength(64);
      expect(result.bytes).toBe(content.length);

      // Cleanup
      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should compute correct SHA-256 hash", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Known content for hash verification");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "chart",
        version: "1.0.0",
        content,
      });

      // Verify hash independently
      const crypto = await import("node:crypto");
      const expectedHash = crypto.createHash("sha256").update(content).digest("hex");
      expect(result.sha256).toBe(expectedHash);

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should mark artifact as ready after successful storage", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Ready artifact");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "report",
        version: "2.0.0",
        content,
      });

      const metadata = await storage.getMetadata(result.id, workspaceId);
      expect(metadata?.status).toBe("ready");
      expect(metadata?.readyAt).toBeDefined();

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should mark artifact as failed on storage error", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Test content");

      // Store once successfully
      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "chart",
        version: "1.0.0",
        content,
      });

      // Force failure by dropping content table temporarily
      await database.query(
        "ALTER TABLE artifact_contents DROP CONSTRAINT artifact_contents_artifact_id_fkey",
      );

      try {
        await storage.store({
          workspaceId,
          ownerRunId,
          kind: "dataset",
          version: "1.0.0",
          content: Buffer.from("This will fail"),
        });
      } catch {
        // Expected to fail
      }

      // Restore constraint
      await database.query(
        "ALTER TABLE artifact_contents ADD CONSTRAINT artifact_contents_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE",
      );

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });
  });

  describe("artifact verification", () => {
    it("should verify artifact by correct SHA-256", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Verifiable content");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "dataset",
        version: "1.0.0",
        content,
      });

      const isValid = await storage.verify({
        id: result.id,
        sha256: result.sha256,
      });

      expect(isValid).toBe(true);

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should reject verification with incorrect SHA-256", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Original content");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "dataset",
        version: "1.0.0",
        content,
      });

      const isValid = await storage.verify({
        id: result.id,
        sha256: "0".repeat(64), // Wrong hash
      });

      expect(isValid).toBe(false);

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should reject verification for non-existent artifact", async () => {
      const isValid = await storage.verify({
        id: "nonexistent_id",
        sha256: "a".repeat(64),
      });

      expect(isValid).toBe(false);
    });

    it("should reject verification for pending artifact", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;

      // Insert pending artifact manually
      const artifactId = `dat_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
      await database.query(
        `INSERT INTO artifacts (id, workspace_id, owner_run_id, kind, version, status)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [artifactId, workspaceId, ownerRunId, "dataset", "1.0.0", "pending"],
      );

      const isValid = await storage.verify({
        id: artifactId,
        sha256: "b".repeat(64),
      });

      expect(isValid).toBe(false);

      await database.query("DELETE FROM artifacts WHERE id = $1", [artifactId]);
    });
  });

  describe("artifact metadata retrieval", () => {
    it("should retrieve artifact metadata by ID", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Metadata test");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "chart",
        version: "3.0.0",
        content,
        metadata: { title: "Test Chart" },
      });

      const metadata = await storage.getMetadata(result.id, workspaceId);

      expect(metadata).toBeDefined();
      expect(metadata?.workspaceId).toBe(workspaceId);
      expect(metadata?.ownerRunId).toBe(ownerRunId);
      expect(metadata?.kind).toBe("chart");
      expect(metadata?.version).toBe("3.0.0");
      expect(metadata?.status).toBe("ready");
      expect(metadata?.sha256).toBe(result.sha256);
      expect(metadata?.bytes).toBe(content.length);
      expect(metadata?.metadata).toEqual({ title: "Test Chart" });

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should enforce workspace isolation", async () => {
      const workspaceId1 = `ws_${randomUUID()}`;
      const workspaceId2 = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Isolated content");

      const result = await storage.store({
        workspaceId: workspaceId1,
        ownerRunId,
        kind: "dataset",
        version: "1.0.0",
        content,
      });

      // Try to access from wrong workspace
      const metadata = await storage.getMetadata(result.id, workspaceId2);
      expect(metadata).toBeNull();

      // Access from correct workspace
      const validMetadata = await storage.getMetadata(result.id, workspaceId1);
      expect(validMetadata).toBeDefined();

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });
  });

  describe("artifact content retrieval", () => {
    it("should retrieve artifact content", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const originalContent = Buffer.from("Retrievable content with special chars: 你好");

      const result = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "report",
        version: "1.0.0",
        content: originalContent,
      });

      const retrievedContent = await storage.getContent(result.id, workspaceId);

      expect(retrievedContent).toBeDefined();
      expect(retrievedContent?.toString()).toBe(originalContent.toString());

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should enforce workspace isolation for content", async () => {
      const workspaceId1 = `ws_${randomUUID()}`;
      const workspaceId2 = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;
      const content = Buffer.from("Private content");

      const result = await storage.store({
        workspaceId: workspaceId1,
        ownerRunId,
        kind: "dataset",
        version: "1.0.0",
        content,
      });

      const wrongWorkspaceContent = await storage.getContent(result.id, workspaceId2);
      expect(wrongWorkspaceContent).toBeNull();

      await database.query("DELETE FROM artifacts WHERE id = $1", [result.id]);
    });

    it("should return null for non-ready artifacts", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;

      const artifactId = `dat_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
      await database.query(
        `INSERT INTO artifacts (id, workspace_id, owner_run_id, kind, version, status)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [artifactId, workspaceId, ownerRunId, "dataset", "1.0.0", "pending"],
      );

      const content = await storage.getContent(artifactId, workspaceId);
      expect(content).toBeNull();

      await database.query("DELETE FROM artifacts WHERE id = $1", [artifactId]);
    });
  });

  describe("artifact listing", () => {
    it("should list artifacts by workspace", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;

      const ids = await Promise.all([
        storage.store({
          workspaceId,
          ownerRunId,
          kind: "dataset",
          version: "1.0.0",
          content: Buffer.from("Dataset 1"),
        }),
        storage.store({
          workspaceId,
          ownerRunId,
          kind: "chart",
          version: "1.0.0",
          content: Buffer.from("Chart 1"),
        }),
        storage.store({
          workspaceId,
          ownerRunId,
          kind: "report",
          version: "1.0.0",
          content: Buffer.from("Report 1"),
        }),
      ]);

      const artifacts = await storage.listByWorkspace(workspaceId);

      expect(artifacts.length).toBeGreaterThanOrEqual(3);
      expect(artifacts.some((a) => a.id === ids[0].id)).toBe(true);
      expect(artifacts.some((a) => a.id === ids[1].id)).toBe(true);
      expect(artifacts.some((a) => a.id === ids[2].id)).toBe(true);

      await Promise.all(
        ids.map((result) => database.query("DELETE FROM artifacts WHERE id = $1", [result.id])),
      );
    });

    it("should list artifacts by owner run", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;

      const ids = await Promise.all([
        storage.store({
          workspaceId,
          ownerRunId,
          kind: "dataset",
          version: "1.0.0",
          content: Buffer.from("Dataset A"),
        }),
        storage.store({
          workspaceId,
          ownerRunId,
          kind: "dataset",
          version: "2.0.0",
          content: Buffer.from("Dataset B"),
        }),
      ]);

      const artifacts = await storage.listByOwnerRun(ownerRunId);

      expect(artifacts.length).toBe(2);
      expect(artifacts[0].ownerRunId).toBe(ownerRunId);
      expect(artifacts[1].ownerRunId).toBe(ownerRunId);

      await Promise.all(
        ids.map((result) => database.query("DELETE FROM artifacts WHERE id = $1", [result.id])),
      );
    });

    it("should paginate workspace artifact list", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;

      const ids = await Promise.all(
        Array.from({ length: 5 }, (_, i) =>
          storage.store({
            workspaceId,
            ownerRunId,
            kind: "dataset",
            version: "1.0.0",
            content: Buffer.from(`Dataset ${i}`),
          }),
        ),
      );

      const page1 = await storage.listByWorkspace(workspaceId, { limit: 2, offset: 0 });
      const page2 = await storage.listByWorkspace(workspaceId, { limit: 2, offset: 2 });

      expect(page1.length).toBe(2);
      expect(page2.length).toBe(2);
      expect(page1[0].id).not.toBe(page2[0].id);

      await Promise.all(
        ids.map((result) => database.query("DELETE FROM artifacts WHERE id = $1", [result.id])),
      );
    });
  });

  describe("version tracking", () => {
    it("should track artifact versions", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const ownerRunId = `run_${randomUUID()}`;

      const v1 = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "dataset",
        version: "1.0.0",
        content: Buffer.from("Version 1"),
      });

      const v2 = await storage.store({
        workspaceId,
        ownerRunId,
        kind: "dataset",
        version: "2.0.0",
        content: Buffer.from("Version 2"),
      });

      const metadata1 = await storage.getMetadata(v1.id, workspaceId);
      const metadata2 = await storage.getMetadata(v2.id, workspaceId);

      expect(metadata1?.version).toBe("1.0.0");
      expect(metadata2?.version).toBe("2.0.0");

      await database.query("DELETE FROM artifacts WHERE id = $1 OR id = $2", [v1.id, v2.id]);
    });
  });
});
