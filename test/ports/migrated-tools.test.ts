import * as fs from "node:fs/promises";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ToolPool } from "../../src/ports/tool-pool.js";
import type { ToolContext } from "../../src/ports/tool-port.js";
import {
  type FileReaderInput,
  fileReaderHandler,
  fileReaderManifest,
} from "../../src/ports/tools/file-reader.js";
import {
  type FileWriterInput,
  fileWriterHandler,
  fileWriterManifest,
} from "../../src/ports/tools/file-writer.js";
import { testScope } from "../helpers/scope.js";

describe("Migrated Tools", () => {
  let pool: ToolPool;
  const testDir = path.join(__dirname, "../../.test-files");

  const scope = testScope();

  beforeEach(async () => {
    pool = new ToolPool();

    // Create test directory
    await fs.mkdir(testDir, { recursive: true });

    // Register tools
    pool.register({
      manifest: fileReaderManifest,
      handler: fileReaderHandler,
      registeredBy: "test",
    });

    pool.register({
      manifest: fileWriterManifest,
      handler: fileWriterHandler,
      registeredBy: "test",
    });
  });

  afterEach(async () => {
    // Clean up test directory
    await fs.rm(testDir, { recursive: true, force: true });
  });

  describe("file-reader", () => {
    it("should read an existing file", async () => {
      const testFile = path.join(testDir, "test.txt");
      await fs.writeFile(testFile, "Hello World", "utf8");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        version: "1.0.0",
        input: { path: testFile },
        context,
      });

      expect(result.status).toBe("success");
      expect(result.output?.content).toBe("Hello World");
      expect(result.output?.size).toBe(11);
      expect(result.evidence).toBeDefined();
    });

    it("should read file with base64 encoding", async () => {
      const testFile = path.join(testDir, "binary.dat");
      const buffer = Buffer.from([0x00, 0x01, 0x02, 0xff]);
      await fs.writeFile(testFile, buffer);

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        version: "1.0.0",
        input: { path: testFile, encoding: "base64" },
        context,
      });

      expect(result.status).toBe("success");
      expect(result.output?.content).toBe(buffer.toString("base64"));
    });

    it("should return error for non-existent file", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        input: { path: path.join(testDir, "missing.txt") },
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.message).toContain("not found");
    });

    it("should reject path with parent directory traversal", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        input: { path: "../../../etc/passwd" },
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.message).toContain("Invalid file path");
    });

    it("should be idempotent", async () => {
      const testFile = path.join(testDir, "idempotent.txt");
      await fs.writeFile(testFile, "Content", "utf8");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
        idempotencyKey: "read-key-1",
      };

      const result1 = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        version: "1.0.0",
        input: { path: testFile },
        context,
      });

      const result2 = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        version: "1.0.0",
        input: { path: testFile },
        context,
      });

      expect(result1.output).toEqual(result2.output);
    });
  });

  describe("file-writer", () => {
    it("should write a new file", async () => {
      const testFile = path.join(testDir, "write-test.txt");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        version: "1.0.0",
        input: {
          path: testFile,
          content: "New content",
        },
        context,
      });

      expect(result.status).toBe("success");
      expect(result.output?.bytesWritten).toBeGreaterThan(0);
      expect(result.evidence).toBeDefined();

      // Verify file was written
      const content = await fs.readFile(testFile, "utf8");
      expect(content).toBe("New content");
    });

    it("should write file with base64 encoding", async () => {
      const testFile = path.join(testDir, "binary-write.dat");
      const buffer = Buffer.from([0xde, 0xad, 0xbe, 0xef]);

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        version: "1.0.0",
        input: {
          path: testFile,
          content: buffer.toString("base64"),
          encoding: "base64",
        },
        context,
      });

      expect(result.status).toBe("success");

      // Verify binary content
      const written = await fs.readFile(testFile);
      expect(Buffer.compare(written, buffer)).toBe(0);
    });

    it("should create parent directories when requested", async () => {
      const testFile = path.join(testDir, "nested", "deep", "file.txt");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        version: "1.0.0",
        input: {
          path: testFile,
          content: "Deep file",
          createDirs: true,
        },
        context,
      });

      expect(result.status).toBe("success");

      const content = await fs.readFile(testFile, "utf8");
      expect(content).toBe("Deep file");
    });

    it("should fail without createDirs when directory missing", async () => {
      const testFile = path.join(testDir, "nonexistent", "file.txt");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        input: {
          path: testFile,
          content: "Content",
          createDirs: false,
        },
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.message).toContain("does not exist");
    });

    it("should reject path with parent directory traversal", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        input: {
          path: "../../../tmp/malicious.txt",
          content: "Bad content",
        },
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.message).toContain("Invalid file path");
    });

    it("should be idempotent for same content", async () => {
      const testFile = path.join(testDir, "idempotent-write.txt");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
        idempotencyKey: "write-key-1",
      };

      const result1 = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        version: "1.0.0",
        input: {
          path: testFile,
          content: "Same content",
        },
        context,
      });

      const result2 = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        version: "1.0.0",
        input: {
          path: testFile,
          content: "Same content",
        },
        context,
      });

      expect(result1.status).toBe("success");
      expect(result2.output).toEqual(result1.output);
    });
  });

  describe("read-write integration", () => {
    it("should write then read a file", async () => {
      const testFile = path.join(testDir, "round-trip.txt");
      const content = "Round trip test";

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      // Write
      const writeResult = await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        version: "1.0.0",
        input: { path: testFile, content },
        context,
      });

      expect(writeResult.status).toBe("success");

      // Read
      const readResult = await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        version: "1.0.0",
        input: { path: testFile },
        context,
      });

      expect(readResult.status).toBe("success");
      expect(readResult.output?.content).toBe(content);
    });

    it("should track both operations in execution history", async () => {
      const testFile = path.join(testDir, "history.txt");

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      await pool.invoke<FileWriterInput, any>({
        toolId: "file-writer",
        input: { path: testFile, content: "Test" },
        context,
      });

      await pool.invoke<FileReaderInput, any>({
        toolId: "file-reader",
        input: { path: testFile },
        context,
      });

      const executions = pool.getRunExecutions("run-1");
      expect(executions).toHaveLength(2);
      expect(executions[0].toolId).toBe("file-writer");
      expect(executions[1].toolId).toBe("file-reader");
    });
  });
});
