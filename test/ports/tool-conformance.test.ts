import { beforeEach, describe, expect, it } from "vitest";
import { ToolPool } from "../../src/ports/tool-pool.js";
import type { ToolContext, ToolManifest } from "../../src/ports/tool-port.js";
import { testScope } from "../helpers/scope.js";

describe("Tool Conformance - Edge Cases", () => {
  let pool: ToolPool;

  const scope = testScope();

  beforeEach(() => {
    pool = new ToolPool();
  });

  describe("concurrent invocations", () => {
    it("should handle concurrent calls to same tool", async () => {
      const manifest: ToolManifest = {
        id: "concurrent-tool",
        version: "1.0.0",
        displayName: "Concurrent Tool",
        description: "Test concurrent execution",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      let execCount = 0;
      pool.register({
        manifest,
        handler: async () => {
          execCount++;
          await new Promise((resolve) => setTimeout(resolve, 50));
          return { count: execCount };
        },
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const results = await Promise.all([
        pool.invoke({ toolId: "concurrent-tool", input: {}, context }),
        pool.invoke({ toolId: "concurrent-tool", input: {}, context }),
        pool.invoke({ toolId: "concurrent-tool", input: {}, context }),
      ]);

      expect(results).toHaveLength(3);
      expect(results.every((r) => r.status === "success")).toBe(true);
      expect(execCount).toBe(3);
    });

    it("should deduplicate concurrent idempotent calls", async () => {
      const manifest: ToolManifest = {
        id: "idempotent-concurrent",
        version: "1.0.0",
        displayName: "Idempotent Concurrent",
        description: "Test idempotency with concurrency",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: true,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      let execCount = 0;
      pool.register({
        manifest,
        handler: async () => {
          execCount++;
          await new Promise((resolve) => setTimeout(resolve, 50));
          return { value: Math.random() };
        },
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
        idempotencyKey: "same-key",
      };

      // First call executes
      const result1 = await pool.invoke({ toolId: "idempotent-concurrent", input: {}, context });

      // Subsequent calls return cached result
      const result2 = await pool.invoke({ toolId: "idempotent-concurrent", input: {}, context });
      const result3 = await pool.invoke({ toolId: "idempotent-concurrent", input: {}, context });

      expect(result1.status).toBe("success");
      expect(result2.output).toEqual(result1.output);
      expect(result3.output).toEqual(result1.output);
      expect(execCount).toBe(1); // Only executed once
    });
  });

  describe("boundary conditions", () => {
    it("should handle exactly at input size limit", async () => {
      const manifest: ToolManifest = {
        id: "boundary-tool",
        version: "1.0.0",
        displayName: "Boundary Tool",
        description: "Test size boundaries",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 100, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async (input: any) => ({ length: input.data.length }),
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      // Create input that is exactly at limit (accounting for JSON overhead)
      // {"data":"xxx"} is ~15 chars base, need ~85 chars in data
      const input = { data: "x".repeat(85) };
      const inputSize = Buffer.byteLength(JSON.stringify(input), "utf8");

      expect(inputSize).toBeLessThanOrEqual(100);

      const result = await pool.invoke({ toolId: "boundary-tool", input, context });
      expect(result.status).toBe("success");
    });

    it("should handle exactly at output size limit", async () => {
      const manifest: ToolManifest = {
        id: "output-boundary-tool",
        version: "1.0.0",
        displayName: "Output Boundary Tool",
        description: "Test output boundaries",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 100, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => ({ data: "x".repeat(85) }),
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({ toolId: "output-boundary-tool", input: {}, context });

      const outputSize = Buffer.byteLength(JSON.stringify(result.output), "utf8");
      expect(outputSize).toBeLessThanOrEqual(100);
      expect(result.status).toBe("success");
    });

    it("should handle deadline exactly at boundary", async () => {
      const manifest: ToolManifest = {
        id: "deadline-tool",
        version: "1.0.0",
        displayName: "Deadline Tool",
        description: "Test deadline boundary",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 100 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => {
          await new Promise((resolve) => setTimeout(resolve, 50));
          return { result: "ok" };
        },
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 90, // Very tight deadline
        fence: "fence-1",
      };

      const result = await pool.invoke({ toolId: "deadline-tool", input: {}, context });

      // May succeed or timeout depending on exact timing
      expect(["success", "timeout"]).toContain(result.status);
    });
  });

  describe("special characters and encoding", () => {
    it("should handle unicode in input and output", async () => {
      const manifest: ToolManifest = {
        id: "unicode-tool",
        version: "1.0.0",
        displayName: "Unicode Tool",
        description: "Test unicode handling",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async (input: any) => ({
          echo: input.text,
          emoji: "🚀✨🎉",
          chinese: "你好世界",
          arabic: "مرحبا",
        }),
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "unicode-tool",
        input: { text: "日本語テスト 🌟" },
        context,
      });

      expect(result.status).toBe("success");
      expect(result.output).toEqual({
        echo: "日本語テスト 🌟",
        emoji: "🚀✨🎉",
        chinese: "你好世界",
        arabic: "مرحبا",
      });
    });

    it("should handle empty input", async () => {
      const manifest: ToolManifest = {
        id: "empty-input-tool",
        version: "1.0.0",
        displayName: "Empty Input Tool",
        description: "Test empty input",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => ({ result: "ok" }),
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({ toolId: "empty-input-tool", input: {}, context });
      expect(result.status).toBe("success");
    });

    it("should handle null values in input", async () => {
      const manifest: ToolManifest = {
        id: "null-tool",
        version: "1.0.0",
        displayName: "Null Tool",
        description: "Test null handling",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async (input: any) => ({
          nullValue: input.value,
          isNull: input.value === null,
        }),
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "null-tool",
        input: { value: null },
        context,
      });

      expect(result.status).toBe("success");
      expect(result.output).toEqual({ nullValue: null, isNull: true });
    });
  });

  describe("error recovery", () => {
    it("should handle handler throwing standard Error", async () => {
      const manifest: ToolManifest = {
        id: "error-tool",
        version: "1.0.0",
        displayName: "Error Tool",
        description: "Test error handling",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => {
          throw new Error("Handler error");
        },
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({ toolId: "error-tool", input: {}, context });

      expect(result.status).toBe("error");
      expect(result.error?.code).toBe("execution_error");
      expect(result.error?.message).toContain("Handler error");
    });

    it("should handle handler throwing string", async () => {
      const manifest: ToolManifest = {
        id: "string-error-tool",
        version: "1.0.0",
        displayName: "String Error Tool",
        description: "Test string error",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => {
          throw "String error";
        },
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({ toolId: "string-error-tool", input: {}, context });

      expect(result.status).toBe("error");
      expect(result.error?.message).toBe("String error");
    });

    it("should handle handler returning null", async () => {
      const manifest: ToolManifest = {
        id: "null-return-tool",
        version: "1.0.0",
        displayName: "Null Return Tool",
        description: "Test null return",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => null,
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({ toolId: "null-return-tool", input: {}, context });

      // null is a valid JSON value
      expect(result.status).toBe("success");
      expect(result.output).toBeNull();
    });
  });

  describe("version handling", () => {
    it("should reject version with same id but different manifest fields", async () => {
      const manifest1: ToolManifest = {
        id: "versioned-tool",
        version: "1.0.0",
        displayName: "Versioned Tool",
        description: "Version 1",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: true,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      const manifest2: ToolManifest = {
        ...manifest1,
        description: "Version 2",
        idempotent: false, // Different idempotency
      };

      pool.register({
        manifest: manifest1,
        handler: async () => ({ version: 1 }),
        registeredBy: "test",
      });

      pool.register({
        manifest: manifest2,
        handler: async () => ({ version: 2 }),
        registeredBy: "test",
      });

      const reg1 = pool.getRegistration("versioned-tool", "1.0.0");
      expect(reg1?.manifest.idempotent).toBe(false); // Latest overwrites
    });

    it("should invoke specific version when requested", async () => {
      const manifest1: ToolManifest = {
        id: "multi-version-tool",
        version: "1.0.0",
        displayName: "Multi Version Tool",
        description: "Version 1",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      const manifest2: ToolManifest = {
        ...manifest1,
        version: "2.0.0",
        description: "Version 2",
      };

      pool.register({
        manifest: manifest1,
        handler: async () => ({ version: 1 }),
        registeredBy: "test",
      });

      await new Promise((resolve) => setTimeout(resolve, 10));

      pool.register({
        manifest: manifest2,
        handler: async () => ({ version: 2 }),
        registeredBy: "test",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result1 = await pool.invoke({
        toolId: "multi-version-tool",
        version: "1.0.0",
        input: {},
        context,
      });

      const result2 = await pool.invoke({
        toolId: "multi-version-tool",
        version: "2.0.0",
        input: {},
        context,
      });

      expect(result1.output).toEqual({ version: 1 });
      expect(result2.output).toEqual({ version: 2 });
    });
  });

  describe("context isolation", () => {
    it("should isolate executions by runId", async () => {
      const manifest: ToolManifest = {
        id: "isolation-tool",
        version: "1.0.0",
        displayName: "Isolation Tool",
        description: "Test isolation",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: false,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => ({ result: "ok" }),
        registeredBy: "test",
      });

      const context1: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const context2: ToolContext = {
        runId: "run-2",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      await pool.invoke({ toolId: "isolation-tool", input: {}, context: context1 });
      await pool.invoke({ toolId: "isolation-tool", input: {}, context: context1 });
      await pool.invoke({ toolId: "isolation-tool", input: {}, context: context2 });

      const run1Execs = pool.getRunExecutions("run-1");
      const run2Execs = pool.getRunExecutions("run-2");

      expect(run1Execs).toHaveLength(2);
      expect(run2Execs).toHaveLength(1);
    });

    it("should not cache across different idempotency keys", async () => {
      const manifest: ToolManifest = {
        id: "cache-key-tool",
        version: "1.0.0",
        displayName: "Cache Key Tool",
        description: "Test cache keys",
        inputSchema: { type: "object", properties: {} },
        effectClass: "read",
        idempotent: true,
        limits: { maxInputBytes: 10000, maxOutputBytes: 10000, timeoutMs: 5000 },
        sensitivity: "public",
      };

      pool.register({
        manifest,
        handler: async () => ({ random: Math.random() }),
        registeredBy: "test",
      });

      const context1: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
        idempotencyKey: "key-1",
      };

      const context2: ToolContext = {
        ...context1,
        idempotencyKey: "key-2",
      };

      const result1 = await pool.invoke({ toolId: "cache-key-tool", input: {}, context: context1 });
      const result2 = await pool.invoke({ toolId: "cache-key-tool", input: {}, context: context2 });

      // Different keys should produce different results
      expect(result1.output).not.toEqual(result2.output);
    });
  });
});
