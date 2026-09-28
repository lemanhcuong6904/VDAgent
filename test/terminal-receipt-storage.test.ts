/**
 * Terminal Receipt Storage Tests - M11.3
 * Validates immutable terminal receipt, identical replay no-op, changed replay conflict
 */

import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrateDatabase } from "../src/database.js";
import { TerminalReceiptStorage } from "../src/terminal-receipt-storage.js";

const databaseUrl = process.env.TEST_DATABASE_URL;
const integration = describe.skipIf(!databaseUrl);
let database: Pool;
let storage: TerminalReceiptStorage;

beforeAll(async () => {
  if (!databaseUrl) return;
  database = new Pool({ connectionString: databaseUrl, max: 6 });
  await migrateDatabase(database);
  storage = new TerminalReceiptStorage(database);
});

afterAll(async () => {
  await database?.end();
});

integration("Terminal Receipt Storage - M11.3", () => {
  describe("seal receipt", () => {
    it("should seal terminal receipt with full metadata", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const input = { task: "analyze_data", params: { dataset: "sales_q3" } };
      const output = { result: "analysis_complete", insights: 15 };

      const receipt = await storage.seal({
        workspaceId,
        runId,
        attemptId,
        status: "success",
        exitCode: 0,
        input,
        output,
        artifactIds: ["dat_abc123", "chart_xyz789"],
        evidenceCount: 10,
        verifiedEvidenceCount: 8,
        durationMs: 45000,
        tokensInput: 1000,
        tokensOutput: 500,
        metadata: { version: "1.0", environment: "production" },
      });

      expect(receipt.id).toMatch(/^rcpt_/);
      expect(receipt.workspaceId).toBe(workspaceId);
      expect(receipt.runId).toBe(runId);
      expect(receipt.status).toBe("success");
      expect(receipt.exitCode).toBe(0);
      expect(receipt.inputHash).toHaveLength(64);
      expect(receipt.outputHash).toHaveLength(64);
      expect(receipt.artifactIds).toEqual(["dat_abc123", "chart_xyz789"]);
      expect(receipt.evidenceCount).toBe(10);
      expect(receipt.verifiedEvidenceCount).toBe(8);
      expect(receipt.durationMs).toBe(45000);
      expect(receipt.tokensInput).toBe(1000);
      expect(receipt.tokensOutput).toBe(500);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });

    it("should compute deterministic input hash", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const input = { task: "process", data: [1, 2, 3] };

      const receipt1 = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input,
      });

      const receipt2 = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt2",
        status: "success",
        input,
      });

      expect(receipt1.inputHash).toBe(receipt2.inputHash);

      await database.query("DELETE FROM terminal_receipts WHERE id IN ($1, $2)", [
        receipt1.id,
        receipt2.id,
      ]);
    });

    it("should handle receipts without output", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const receipt = await storage.seal({
        workspaceId,
        runId,
        attemptId: "attempt1",
        status: "failure",
        exitCode: 1,
        input: { task: "fail_task" },
      });

      expect(receipt.outputHash).toBeNull();
      expect(receipt.status).toBe("failure");
      expect(receipt.exitCode).toBe(1);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });

    it("should enforce immutability via unique constraint", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;
      const attemptId = `attempt_${randomUUID()}`;

      const receipt1 = await storage.seal({
        workspaceId,
        runId,
        attemptId,
        status: "success",
        input: { task: "first" },
      });

      await expect(
        storage.seal({
          workspaceId,
          runId,
          attemptId,
          status: "success",
          input: { task: "second" },
        }),
      ).rejects.toThrow();

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt1.id]);
    });
  });

  describe("replay detection", () => {
    it("should detect identical replay (no-op)", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const input = { task: "idempotent_operation", value: 42 };

      const receipt = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input,
        output: { result: "done" },
      });

      const replayCheck = await storage.checkReplay(workspaceId, input);

      expect(replayCheck.exists).toBe(true);
      expect(replayCheck.identical).toBe(true);
      expect(replayCheck.conflict).toBe(false);
      expect(replayCheck.existingReceipt?.id).toBe(receipt.id);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });

    it("should not detect replay for new input", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const newInput = { task: "never_seen_before", value: 999 };

      const replayCheck = await storage.checkReplay(workspaceId, newInput);

      expect(replayCheck.exists).toBe(false);
      expect(replayCheck.identical).toBe(false);
      expect(replayCheck.conflict).toBe(false);
      expect(replayCheck.existingReceipt).toBeUndefined();
    });

    it("should enforce workspace isolation for replay", async () => {
      const workspaceId1 = `ws_${randomUUID()}`;
      const workspaceId2 = `ws_${randomUUID()}`;
      const input = { task: "isolated_task" };

      const receipt = await storage.seal({
        workspaceId: workspaceId1,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input,
      });

      const replayCheck = await storage.checkReplay(workspaceId2, input);

      expect(replayCheck.exists).toBe(false);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });
  });

  describe("conflict detection", () => {
    it("should detect no conflict for identical output", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const input = { task: "deterministic" };
      const output = { result: "always_same" };

      const receipt = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input,
        output,
      });

      const conflictCheck = await storage.checkConflict(workspaceId, input, output);

      expect(conflictCheck.exists).toBe(true);
      expect(conflictCheck.identical).toBe(true);
      expect(conflictCheck.conflict).toBe(false);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });

    it("should detect conflict for different output", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const input = { task: "non_deterministic" };

      const receipt = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input,
        output: { result: "first_run", timestamp: 1000 },
      });

      const conflictCheck = await storage.checkConflict(workspaceId, input, {
        result: "second_run",
        timestamp: 2000,
      });

      expect(conflictCheck.exists).toBe(true);
      expect(conflictCheck.identical).toBe(false);
      expect(conflictCheck.conflict).toBe(true);
      expect(conflictCheck.existingReceipt?.id).toBe(receipt.id);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });
  });

  describe("receipt retrieval", () => {
    it("should retrieve receipt by ID", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const sealed = await storage.seal({
        workspaceId,
        runId,
        attemptId: "attempt1",
        status: "success",
        input: { task: "retrieve_test" },
        metadata: { custom: "value" },
      });

      const retrieved = await storage.get(sealed.id, workspaceId);

      expect(retrieved).toBeDefined();
      expect(retrieved?.id).toBe(sealed.id);
      expect(retrieved?.runId).toBe(runId);
      expect(retrieved?.metadata).toEqual({ custom: "value" });

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [sealed.id]);
    });

    it("should retrieve receipt by run ID", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const runId = `run_${randomUUID()}`;

      const sealed = await storage.seal({
        workspaceId,
        runId,
        attemptId: "attempt1",
        status: "success",
        input: { task: "run_test" },
      });

      const retrieved = await storage.getByRun(runId, workspaceId);

      expect(retrieved).toBeDefined();
      expect(retrieved?.runId).toBe(runId);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [sealed.id]);
    });

    it("should enforce workspace isolation", async () => {
      const workspaceId1 = `ws_${randomUUID()}`;
      const workspaceId2 = `ws_${randomUUID()}`;

      const sealed = await storage.seal({
        workspaceId: workspaceId1,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input: { task: "secret" },
      });

      const wrongWorkspace = await storage.get(sealed.id, workspaceId2);
      expect(wrongWorkspace).toBeNull();

      const correctWorkspace = await storage.get(sealed.id, workspaceId1);
      expect(correctWorkspace).toBeDefined();

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [sealed.id]);
    });
  });

  describe("receipt listing", () => {
    it("should list receipts by workspace", async () => {
      const workspaceId = `ws_${randomUUID()}`;

      const ids = await Promise.all([
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt1",
          status: "success",
          input: { task: "task1" },
        }),
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt2",
          status: "failure",
          input: { task: "task2" },
        }),
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt3",
          status: "success",
          input: { task: "task3" },
        }),
      ]);

      const receipts = await storage.listByWorkspace(workspaceId);

      expect(receipts.length).toBeGreaterThanOrEqual(3);
      expect(receipts.some((r) => r.id === ids[0].id)).toBe(true);
      expect(receipts.some((r) => r.id === ids[1].id)).toBe(true);
      expect(receipts.some((r) => r.id === ids[2].id)).toBe(true);

      await Promise.all(
        ids.map((receipt) =>
          database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]),
        ),
      );
    });

    it("should list receipts by status", async () => {
      const workspaceId = `ws_${randomUUID()}`;

      const success1 = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input: { task: "task1" },
      });

      const success2 = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt2",
        status: "success",
        input: { task: "task2" },
      });

      const failure = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt3",
        status: "failure",
        input: { task: "task3" },
      });

      const successes = await storage.listByStatus(workspaceId, "success");

      expect(successes.some((r) => r.id === success1.id)).toBe(true);
      expect(successes.some((r) => r.id === success2.id)).toBe(true);
      expect(successes.every((r) => r.status === "success")).toBe(true);

      await Promise.all(
        [success1, success2, failure].map((receipt) =>
          database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]),
        ),
      );
    });

    it("should paginate workspace listing", async () => {
      const workspaceId = `ws_${randomUUID()}`;

      const ids = await Promise.all(
        Array.from({ length: 5 }, (_, i) =>
          storage.seal({
            workspaceId,
            runId: `run_${randomUUID()}`,
            attemptId: `attempt${i}`,
            status: "success",
            input: { task: `task${i}` },
          }),
        ),
      );

      const page1 = await storage.listByWorkspace(workspaceId, { limit: 2, offset: 0 });
      const page2 = await storage.listByWorkspace(workspaceId, { limit: 2, offset: 2 });

      expect(page1.length).toBe(2);
      expect(page2.length).toBe(2);
      expect(page1[0].id).not.toBe(page2[0].id);

      await Promise.all(
        ids.map((receipt) =>
          database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]),
        ),
      );
    });
  });

  describe("status counting", () => {
    it("should count receipts by status", async () => {
      const workspaceId = `ws_${randomUUID()}`;

      const receipts = await Promise.all([
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt1",
          status: "success",
          input: { task: "task1" },
        }),
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt2",
          status: "success",
          input: { task: "task2" },
        }),
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt3",
          status: "failure",
          input: { task: "task3" },
        }),
        storage.seal({
          workspaceId,
          runId: `run_${randomUUID()}`,
          attemptId: "attempt4",
          status: "timeout",
          input: { task: "task4" },
        }),
      ]);

      const counts = await storage.countByStatus(workspaceId);

      expect(counts.success).toBeGreaterThanOrEqual(2);
      expect(counts.failure).toBeGreaterThanOrEqual(1);
      expect(counts.timeout).toBeGreaterThanOrEqual(1);

      await Promise.all(
        receipts.map((receipt) =>
          database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]),
        ),
      );
    });
  });

  describe("resource tracking", () => {
    it("should track duration and token usage", async () => {
      const workspaceId = `ws_${randomUUID()}`;

      const receipt = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input: { task: "resource_task" },
        durationMs: 12345,
        tokensInput: 500,
        tokensOutput: 300,
      });

      expect(receipt.durationMs).toBe(12345);
      expect(receipt.tokensInput).toBe(500);
      expect(receipt.tokensOutput).toBe(300);

      // duration_ms is bigint; the read path must return a number, not pg's string
      const retrieved = await storage.get(receipt.id, workspaceId);
      expect(retrieved?.durationMs).toBe(12345);
      expect(retrieved?.tokensInput).toBe(500);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });

    it("should track artifact IDs", async () => {
      const workspaceId = `ws_${randomUUID()}`;
      const artifactIds = ["dat_result1", "chart_viz2", "report_summary3"];

      const receipt = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input: { task: "create_artifacts" },
        artifactIds,
      });

      expect(receipt.artifactIds).toEqual(artifactIds);

      const retrieved = await storage.get(receipt.id, workspaceId);
      expect(retrieved?.artifactIds).toEqual(artifactIds);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });

    it("should track evidence counts", async () => {
      const workspaceId = `ws_${randomUUID()}`;

      const receipt = await storage.seal({
        workspaceId,
        runId: `run_${randomUUID()}`,
        attemptId: "attempt1",
        status: "success",
        input: { task: "evidence_task" },
        evidenceCount: 25,
        verifiedEvidenceCount: 20,
      });

      expect(receipt.evidenceCount).toBe(25);
      expect(receipt.verifiedEvidenceCount).toBe(20);

      await database.query("DELETE FROM terminal_receipts WHERE id = $1", [receipt.id]);
    });
  });
});
