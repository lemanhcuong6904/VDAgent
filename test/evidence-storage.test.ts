/**
 * Evidence Storage Tests - M11.2
 * Validates evidence refs linking source/run/tool/model/artifact revision
 */

import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ArtifactStorage } from "../src/artifact-storage.js";
import { migrateDatabase } from "../src/database.js";
import { EvidenceStorage } from "../src/evidence-storage.js";

const databaseUrl = process.env.TEST_DATABASE_URL;
const integration = describe.skipIf(!databaseUrl);
let database: Pool;
let storage: EvidenceStorage;

beforeAll(async () => {
  if (!databaseUrl) return;
  database = new Pool({ connectionString: databaseUrl, max: 6 });
  await migrateDatabase(database);
  storage = new EvidenceStorage(database);
});

afterAll(async () => {
  await database?.end();
});

integration("Evidence Storage - M11.2", () => {
  describe("source evidence", () => {
    it("should record source evidence", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const evidenceId = await storage.recordSource({
        workspaceId,
        runId,
        attemptId,
        sourceType: "git",
        sourceLocation: "https://github.com/org/repo.git",
        sourceRevision: "abc123def456",
        metadata: { branch: "main" },
      });

      expect(evidenceId).toMatch(/^src_/);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence).toBeDefined();
      expect(evidence?.kind).toBe("source");
      expect(evidence?.verification).toBe("unverified");

      if (evidence?.kind === "source") {
        expect(evidence.sourceType).toBe("git");
        expect(evidence.sourceLocation).toBe("https://github.com/org/repo.git");
        expect(evidence.sourceRevision).toBe("abc123def456");
      }

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });
  });

  describe("tool call evidence", () => {
    it("should record tool call with input/output hashes", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const toolInput = { query: "SELECT * FROM users" };
      const toolOutput = { rows: [{ id: 1, name: "Alice" }] };

      const evidenceId = await storage.recordToolCall({
        workspaceId,
        runId,
        attemptId,
        toolId: "warehouse.query",
        toolInput,
        toolOutput,
        metadata: { duration: 123 },
      });

      expect(evidenceId).toMatch(/^tool_/);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence).toBeDefined();
      expect(evidence?.kind).toBe("tool_call");

      if (evidence?.kind === "tool_call") {
        expect(evidence.toolId).toBe("warehouse.query");
        expect(evidence.toolInputHash).toHaveLength(64);
        expect(evidence.toolOutputHash).toHaveLength(64);
      }

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });

    it("should produce deterministic hashes for same input", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const toolInput = { param: "value" };
      const toolOutput = { result: "success" };

      const evidence1Id = await storage.recordToolCall({
        workspaceId,
        runId,
        attemptId: "attempt1",
        toolId: "test.tool",
        toolInput,
        toolOutput,
      });

      const evidence2Id = await storage.recordToolCall({
        workspaceId,
        runId,
        attemptId: "attempt2",
        toolId: "test.tool",
        toolInput,
        toolOutput,
      });

      const evidence1 = await storage.get(evidence1Id, workspaceId);
      const evidence2 = await storage.get(evidence2Id, workspaceId);

      if (evidence1?.kind === "tool_call" && evidence2?.kind === "tool_call") {
        expect(evidence1.toolInputHash).toBe(evidence2.toolInputHash);
        expect(evidence1.toolOutputHash).toBe(evidence2.toolOutputHash);
      }

      await database.query("DELETE FROM evidence_refs WHERE id IN ($1, $2)", [
        evidence1Id,
        evidence2Id,
      ]);
    });

    it("canonicalizes object key order before hashing", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const first = await storage.recordToolCall({
        workspaceId,
        runId,
        attemptId: "attempt1",
        toolId: "test.tool",
        toolInput: { a: 1, b: 2 },
        toolOutput: { ok: true },
      });
      const second = await storage.recordToolCall({
        workspaceId,
        runId,
        attemptId: "attempt2",
        toolId: "test.tool",
        toolInput: { b: 2, a: 1 },
        toolOutput: { ok: true },
      });
      const firstEvidence = await storage.get(first, workspaceId);
      const secondEvidence = await storage.get(second, workspaceId);
      if (firstEvidence?.kind === "tool_call" && secondEvidence?.kind === "tool_call") {
        expect(firstEvidence.toolInputHash).toBe(secondEvidence.toolInputHash);
      }
      await database.query("DELETE FROM evidence_refs WHERE id IN ($1, $2)", [first, second]);
    });
  });

  describe("model call evidence", () => {
    it("should record model call with token counts", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const evidenceId = await storage.recordModelCall({
        workspaceId,
        runId,
        attemptId,
        modelId: "claude-opus-4",
        modelInput: "Summarize this text",
        modelOutput: "Brief summary here",
        tokens: { input: 10, output: 5, cacheRead: 20, cacheWrite: 0 },
        metadata: { temperature: 0.7 },
      });

      expect(evidenceId).toMatch(/^model_/);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence).toBeDefined();
      expect(evidence?.kind).toBe("model_call");

      if (evidence?.kind === "model_call") {
        expect(evidence.modelId).toBe("claude-opus-4");
        expect(evidence.modelInputHash).toHaveLength(64);
        expect(evidence.modelOutputHash).toHaveLength(64);
        expect(evidence.modelTokens.input).toBe(10);
        expect(evidence.modelTokens.output).toBe(5);
      }

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });
  });

  describe("artifact reference evidence", () => {
    it("should record artifact reference", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const evidenceId = await storage.recordArtifactRef({
        workspaceId,
        runId,
        attemptId,
        artifactId: "dat_abc123",
        artifactSha256: "a".repeat(64),
        metadata: { kind: "dataset" },
      });

      expect(evidenceId).toMatch(/^art_/);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence).toBeDefined();
      expect(evidence?.kind).toBe("artifact_ref");

      if (evidence?.kind === "artifact_ref") {
        expect(evidence.artifactId).toBe("dat_abc123");
        expect(evidence.artifactSha256).toBe("a".repeat(64));
      }

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });

    it("should list artifact references by artifact ID", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId1 = `run_${randomUUID()}`;
      const runId2 = `run_${randomUUID()}`;
      const artifactId = "dat_shared";

      const evidence1Id = await storage.recordArtifactRef({
        workspaceId,
        runId: runId1,
        attemptId: "attempt1",
        artifactId,
        artifactSha256: "b".repeat(64),
      });

      const evidence2Id = await storage.recordArtifactRef({
        workspaceId,
        runId: runId2,
        attemptId: "attempt2",
        artifactId,
        artifactSha256: "b".repeat(64),
      });

      const references = await storage.listByArtifact(artifactId, workspaceId);

      expect(references.length).toBe(2);
      expect(references.some((r) => r.runId === runId1)).toBe(true);
      expect(references.some((r) => r.runId === runId2)).toBe(true);

      await database.query("DELETE FROM evidence_refs WHERE id IN ($1, $2)", [
        evidence1Id,
        evidence2Id,
      ]);
    });

    it("strictly binds artifact evidence to ready bytes and workspace", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const artifacts = new ArtifactStorage(database);
      const strict = new EvidenceStorage(database, {
        requireArtifactVerification: true,
      });
      const stored = await artifacts.store({
        workspaceId,
        ownerRunId: runId,
        kind: "dataset",
        version: "1",
        content: Buffer.from("evidence-bytes"),
      });
      await expect(
        strict.recordArtifactRef({
          workspaceId,
          runId,
          attemptId: "attempt-strict",
          artifactId: stored.id,
          artifactSha256: "0".repeat(64),
        }),
      ).rejects.toThrow("artifact_ref_not_verifiable");
      const evidenceId = await strict.recordArtifactRef({
        workspaceId,
        runId,
        attemptId: "attempt-strict",
        artifactId: stored.id,
        artifactSha256: stored.sha256,
      });
      await expect(strict.markVerified(evidenceId, "ws_other")).resolves.toBe(false);
      await expect(strict.markVerified(evidenceId, workspaceId)).resolves.toBe(true);
      const tamperedArtifact = await artifacts.store({
        workspaceId,
        ownerRunId: runId,
        kind: "dataset",
        version: "1",
        content: Buffer.from("before-tampering"),
      });
      const tamperedEvidence = await strict.recordArtifactRef({
        workspaceId,
        runId,
        attemptId: "attempt-tampered",
        artifactId: tamperedArtifact.id,
        artifactSha256: tamperedArtifact.sha256,
      });
      await database.query("UPDATE artifact_contents SET content = $2 WHERE artifact_id = $1", [
        tamperedArtifact.id,
        Buffer.from("after-tampering"),
      ]);
      await expect(strict.markVerified(tamperedEvidence, workspaceId)).resolves.toBe(false);
      expect((await strict.get(tamperedEvidence, workspaceId))?.verification).toBe("unavailable");
      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
      await database.query("DELETE FROM evidence_refs WHERE id = $1", [tamperedEvidence]);
      await database.query("DELETE FROM artifacts WHERE id = $1", [stored.id]);
      await database.query("DELETE FROM artifacts WHERE id = $1", [tamperedArtifact.id]);
    });
  });

  describe("checkpoint evidence", () => {
    it("should record checkpoint", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const evidenceId = await storage.recordCheckpoint({
        workspaceId,
        runId,
        attemptId,
        checkpointId: "ckpt_20260927_001",
        checkpointRevision: 5,
        metadata: { step: "after_validation" },
      });

      expect(evidenceId).toMatch(/^ckpt_/);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence).toBeDefined();
      expect(evidence?.kind).toBe("checkpoint");

      if (evidence?.kind === "checkpoint") {
        expect(evidence.checkpointId).toBe("ckpt_20260927_001");
        expect(evidence.checkpointRevision).toBe(5);
      }

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });
  });

  describe("verification status", () => {
    it("should mark evidence as verified", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const evidenceId = await storage.recordSource({
        workspaceId,
        runId,
        attemptId,
        sourceType: "file",
        sourceLocation: "/path/to/file.ts",
        sourceRevision: "v1.0.0",
      });

      await expect(storage.markUnavailable(evidenceId, "ws_other")).resolves.toBe(false);
      await storage.markVerified(evidenceId, workspaceId);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence?.verification).toBe("verified");
      expect(evidence?.verifiedAt).toBeDefined();

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });

    it("should mark evidence as unavailable", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const evidenceId = await storage.recordArtifactRef({
        workspaceId,
        runId,
        attemptId,
        artifactId: "dat_deleted",
        artifactSha256: "c".repeat(64),
      });

      await storage.markUnavailable(evidenceId, workspaceId);

      const evidence = await storage.get(evidenceId, workspaceId);
      expect(evidence?.verification).toBe("unavailable");

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });

    it("should count evidence by verification status", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const _unverifiedId = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt1",
        sourceType: "git",
        sourceLocation: "repo1",
        sourceRevision: "rev1",
      });

      const verifiedId = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt2",
        sourceType: "git",
        sourceLocation: "repo2",
        sourceRevision: "rev2",
      });
      await storage.markVerified(verifiedId, workspaceId);

      const unavailableId = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt3",
        sourceType: "git",
        sourceLocation: "repo3",
        sourceRevision: "rev3",
      });
      await storage.markUnavailable(unavailableId, workspaceId);

      const counts = await storage.countByStatus(runId, workspaceId);

      expect(counts.unverified).toBe(1);
      expect(counts.verified).toBe(1);
      expect(counts.unavailable).toBe(1);

      await database.query("DELETE FROM evidence_refs WHERE run_id = $1", [runId]);
    });
  });

  describe("evidence retrieval", () => {
    it("should list all evidence by run", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const sourceId = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt1",
        sourceType: "file",
        sourceLocation: "/src/app.ts",
        sourceRevision: "v2.0.0",
      });

      const toolId = await storage.recordToolCall({
        workspaceId,
        runId,
        attemptId: "attempt2",
        toolId: "read_file",
        toolInput: { path: "/src/app.ts" },
        toolOutput: { content: "..." },
      });

      const modelId = await storage.recordModelCall({
        workspaceId,
        runId,
        attemptId: "attempt3",
        modelId: "claude-sonnet-4",
        modelInput: "Analyze this code",
        modelOutput: "Analysis result",
        tokens: { input: 100, output: 50 },
      });

      const evidence = await storage.listByRun(runId, workspaceId);

      expect(evidence.length).toBe(3);
      expect(evidence.some((e) => e.kind === "source")).toBe(true);
      expect(evidence.some((e) => e.kind === "tool_call")).toBe(true);
      expect(evidence.some((e) => e.kind === "model_call")).toBe(true);

      await database.query("DELETE FROM evidence_refs WHERE id IN ($1, $2, $3)", [
        sourceId,
        toolId,
        modelId,
      ]);
    });

    it("should enforce workspace isolation", async () => {
      const workspaceId1 = `ws_${randomUUID()}`;
      const workspaceId2 = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const evidenceId = await storage.recordSource({
        workspaceId: workspaceId1,
        runId,
        attemptId: "attempt1",
        sourceType: "file",
        sourceLocation: "/secret/file.ts",
        sourceRevision: "v1.0.0",
      });

      const wrongWorkspaceEvidence = await storage.get(evidenceId, workspaceId2);
      expect(wrongWorkspaceEvidence).toBeNull();

      const correctWorkspaceEvidence = await storage.get(evidenceId, workspaceId1);
      expect(correctWorkspaceEvidence).toBeDefined();

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });

    it("should return evidence in chronological order", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const id1 = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt1",
        sourceType: "file",
        sourceLocation: "/file1.ts",
        sourceRevision: "v1",
      });

      await new Promise((resolve) => setTimeout(resolve, 10));

      const id2 = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt2",
        sourceType: "file",
        sourceLocation: "/file2.ts",
        sourceRevision: "v2",
      });

      await new Promise((resolve) => setTimeout(resolve, 10));

      const id3 = await storage.recordSource({
        workspaceId,
        runId,
        attemptId: "attempt3",
        sourceType: "file",
        sourceLocation: "/file3.ts",
        sourceRevision: "v3",
      });

      const evidence = await storage.listByRun(runId, workspaceId);

      expect(evidence[0].id).toBe(id1);
      expect(evidence[1].id).toBe(id2);
      expect(evidence[2].id).toBe(id3);

      await database.query("DELETE FROM evidence_refs WHERE run_id = $1", [runId]);
    });
  });

  describe("metadata storage", () => {
    it("should preserve custom metadata", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const evidenceId = await storage.recordModelCall({
        workspaceId,
        runId,
        attemptId: "attempt1",
        modelId: "claude-opus-5",
        modelInput: "Test",
        modelOutput: "Result",
        tokens: { input: 5, output: 3 },
        metadata: {
          temperature: 0.9,
          maxTokens: 100,
          stop: ["END"],
          custom: { nested: { value: 42 } },
        },
      });

      const evidence = await storage.get(evidenceId, workspaceId);

      expect(evidence?.metadata).toEqual({
        temperature: 0.9,
        maxTokens: 100,
        stop: ["END"],
        custom: { nested: { value: 42 } },
      });

      await database.query("DELETE FROM evidence_refs WHERE id = $1", [evidenceId]);
    });
  });
});
