import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToolPool } from "../../src/ports/tool-pool.js";
import type { ToolContext, ToolManifest } from "../../src/ports/tool-port.js";
import { testScope } from "../helpers/scope.js";

describe("ToolPool", () => {
  let pool: ToolPool;

  const sampleManifest: ToolManifest = {
    id: "test-tool",
    version: "1.0.0",
    displayName: "Test Tool",
    description: "A test tool",
    inputSchema: { type: "object", properties: { message: { type: "string" } } },
    outputSchema: { type: "object", properties: { result: { type: "string" } } },
    effectClass: "read",
    idempotent: true,
    limits: {
      maxInputBytes: 10000,
      maxOutputBytes: 10000,
      timeoutMs: 5000,
    },
    sensitivity: "public",
  };

  const sampleScope = testScope();

  beforeEach(() => {
    pool = new ToolPool();
  });

  describe("register", () => {
    it("should register a tool", () => {
      pool.register({
        manifest: sampleManifest,
        handler: async (_input) => ({ result: "ok" }),
        registeredBy: "user-1",
      });

      const registration = pool.getRegistration("test-tool", "1.0.0");
      expect(registration).toBeDefined();
      expect(registration?.manifest.id).toBe("test-tool");
    });

    it("should reject invalid manifest", () => {
      const invalidManifest = { ...sampleManifest };
      delete (invalidManifest as any).id;

      expect(() =>
        pool.register({
          manifest: invalidManifest as ToolManifest,
          handler: async (_input) => ({ result: "ok" }),
          registeredBy: "user-1",
        }),
      ).toThrow("Invalid tool manifest");
    });

    it("should handle multiple versions", () => {
      pool.register({
        manifest: sampleManifest,
        handler: async (_input) => ({ result: "v1" }),
        registeredBy: "user-1",
      });

      pool.register({
        manifest: { ...sampleManifest, version: "2.0.0" },
        handler: async (_input) => ({ result: "v2" }),
        registeredBy: "user-1",
      });

      const v1 = pool.getRegistration("test-tool", "1.0.0");
      const v2 = pool.getRegistration("test-tool", "2.0.0");

      expect(v1).toBeDefined();
      expect(v2).toBeDefined();
      expect(v1?.manifest.version).toBe("1.0.0");
      expect(v2?.manifest.version).toBe("2.0.0");
    });
  });

  describe("invoke", () => {
    beforeEach(() => {
      pool.register({
        manifest: sampleManifest,
        handler: async (input: any) => {
          await new Promise((resolve) => setTimeout(resolve, 10));
          return { result: `Hello ${input.message}` };
        },
        registeredBy: "user-1",
      });
    });

    it("should invoke a tool successfully", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "World" },
        context,
      });

      expect(result.status).toBe("success");
      expect(result.output).toEqual({ result: "Hello World" });
      expect(result.evidence).toBeDefined();
      expect(result.usage?.durationMs).toBeGreaterThan(0);
    });

    it("should return error for non-existent tool", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "unknown-tool",
        input: {},
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.code).toBe("tool_not_found");
      expect(result.error?.retryable).toBe(false);
    });

    it("should enforce input size limits", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const largeInput = { message: "x".repeat(20000) };

      const result = await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: largeInput,
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.code).toBe("input_too_large");
    });

    it("should enforce output size limits", async () => {
      pool.register({
        manifest: {
          ...sampleManifest,
          id: "large-output-tool",
        },
        handler: async (_input: any) => ({ result: "x".repeat(20000) }),
        registeredBy: "user-1",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "large-output-tool",
        input: { message: "test" },
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.code).toBe("output_too_large");
    });

    it("should handle timeout", async () => {
      pool.register({
        manifest: {
          ...sampleManifest,
          id: "slow-tool",
          limits: {
            ...sampleManifest.limits,
            timeoutMs: 100,
          },
        },
        handler: async (_input: any) => {
          await new Promise((resolve) => setTimeout(resolve, 500));
          return { result: "done" };
        },
        registeredBy: "user-1",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "slow-tool",
        input: { message: "test" },
        context,
      });

      expect(result.status).toBe("timeout");
      expect(result.error?.code).toBe("timeout");
      expect(result.error?.retryable).toBe(true);
    });

    it("should validate output schema", async () => {
      pool.register({
        manifest: {
          ...sampleManifest,
          id: "invalid-output-tool",
        },
        handler: async (_input: any) => ({ wrong: "field" }),
        registeredBy: "user-1",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "invalid-output-tool",
        input: { message: "test" },
        context,
      });

      expect(result.status).toBe("error");
      expect(result.error?.code).toBe("invalid_output");
    });

    it("should check deadline before invocation", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() - 1000, // Already passed
        fence: "fence-1",
      };

      const result = await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test" },
        context,
      });

      expect(result.status).toBe("timeout");
      expect(result.error?.code).toBe("deadline_exceeded");
    });
  });

  describe("idempotency", () => {
    beforeEach(() => {
      pool.register({
        manifest: sampleManifest,
        handler: async (_input: any) => ({ result: `${Math.random()}` }),
        registeredBy: "user-1",
      });
    });

    it("should cache idempotent tool results", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
        idempotencyKey: "key-1",
      };

      const result1 = await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test" },
        context,
      });

      const result2 = await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test" },
        context,
      });

      expect(result1.status).toBe("success");
      expect(result2.status).toBe("success");
      expect(result1.output).toEqual(result2.output);
    });

    it("should reject reuse of an idempotency key with different input", async () => {
      const handler = vi.fn(async (input: { message: string }) => ({ result: input.message }));
      pool.register({ manifest: sampleManifest, handler, registeredBy: "user-1" });
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10_000,
        fence: "fence-1",
        idempotencyKey: "same-key",
      };

      const first = await pool.invoke({
        toolId: "test-tool",
        input: { message: "first" },
        context,
      });
      const conflict = await pool.invoke({
        toolId: "test-tool",
        input: { message: "different" },
        context,
      });

      expect(first.status).toBe("success");
      expect(conflict).toMatchObject({ status: "error", error: { code: "idempotency_conflict" } });
      expect(handler).toHaveBeenCalledOnce();
    });

    it("should share a concurrent in-flight call for the same key and input", async () => {
      const handler = vi.fn(async (input: { message: string }) => {
        await new Promise((resolve) => setTimeout(resolve, 10));
        return { result: input.message };
      });
      pool.register({ manifest: sampleManifest, handler, registeredBy: "user-1" });
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10_000,
        fence: "fence-1",
        idempotencyKey: "same-key",
      };
      const invocation = { toolId: "test-tool", input: { message: "same" }, context };

      const [first, second] = await Promise.all([pool.invoke(invocation), pool.invoke(invocation)]);

      expect(first.status).toBe("success");
      expect(second).toEqual(first);
      expect(handler).toHaveBeenCalledOnce();
    });

    it("should not cache non-idempotent tools", async () => {
      pool.register({
        manifest: {
          ...sampleManifest,
          id: "non-idempotent-tool",
          idempotent: false,
        },
        handler: async (_input: any) => ({ result: `${Math.random()}` }),
        registeredBy: "user-1",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
        idempotencyKey: "key-1",
      };

      const result1 = await pool.invoke({
        toolId: "non-idempotent-tool",
        input: { message: "test" },
        context,
      });

      const result2 = await pool.invoke({
        toolId: "non-idempotent-tool",
        input: { message: "test" },
        context,
      });

      expect(result1.status).toBe("success");
      expect(result2.status).toBe("success");
      // Random values should be different
      expect(result1.output).not.toEqual(result2.output);
    });
  });

  describe("tool port", () => {
    beforeEach(() => {
      pool.register({
        manifest: sampleManifest,
        handler: async (_input: any) => ({ result: "ok" }),
        registeredBy: "user-1",
      });
    });

    it("should create tool port", () => {
      const port = pool.createToolPort("run-1", "attempt-1", sampleScope);
      expect(port).toBeDefined();
      expect(port.invoke).toBeDefined();
      expect(port.available).toBeDefined();
      expect(port.getManifest).toBeDefined();
    });

    it("should check tool availability", async () => {
      const port = pool.createToolPort("run-1", "attempt-1", sampleScope);

      const available = await port.available("test-tool", "1.0.0");
      expect(available).toBe(true);

      const notAvailable = await port.available("unknown-tool");
      expect(notAvailable).toBe(false);
    });

    it("should get tool manifest", async () => {
      const port = pool.createToolPort("run-1", "attempt-1", sampleScope);

      const manifest = await port.getManifest("test-tool", "1.0.0");
      expect(manifest).toBeDefined();
      expect(manifest?.id).toBe("test-tool");
    });
  });

  describe("execution tracking", () => {
    beforeEach(() => {
      pool.register({
        manifest: sampleManifest,
        handler: async (_input: any) => {
          await new Promise((resolve) => setTimeout(resolve, 10));
          return { result: "ok" };
        },
        registeredBy: "user-1",
      });
    });

    it("should track executions for a run", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test1" },
        context,
      });

      await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test2" },
        context,
      });

      const executions = pool.getRunExecutions("run-1");
      expect(executions).toHaveLength(2);
      expect(executions[0].status).toBe("success");
      expect(executions[1].status).toBe("success");
    });

    it("should compute statistics", async () => {
      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test1" },
        context,
      });

      await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test2" },
        context,
      });

      const stats = pool.getStatistics({ runId: "run-1" });
      expect(stats.totalExecutions).toBe(2);
      expect(stats.successCount).toBe(2);
      expect(stats.errorCount).toBe(0);
      expect(stats.averageDurationMs).toBeGreaterThan(0);
    });

    it("should filter statistics by tool", async () => {
      pool.register({
        manifest: {
          ...sampleManifest,
          id: "tool-2",
        },
        handler: async (_input: any) => ({ result: "ok" }),
        registeredBy: "user-1",
      });

      const context: ToolContext = {
        runId: "run-1",
        attemptId: "attempt-1",
        scope: sampleScope,
        deadline: Date.now() + 10000,
        fence: "fence-1",
      };

      await pool.invoke({
        toolId: "test-tool",
        version: "1.0.0",
        input: { message: "test" },
        context,
      });

      await pool.invoke({
        toolId: "tool-2",
        input: { message: "test" },
        context,
      });

      const stats = pool.getStatistics({ toolId: "test-tool" });
      expect(stats.totalExecutions).toBe(1);
    });
  });

  describe("list operations", () => {
    it("should list all tools", () => {
      pool.register({
        manifest: sampleManifest,
        handler: async (_input: any) => ({ result: "ok" }),
        registeredBy: "user-1",
      });

      pool.register({
        manifest: { ...sampleManifest, version: "2.0.0" },
        handler: async (_input: any) => ({ result: "ok" }),
        registeredBy: "user-1",
      });

      pool.register({
        manifest: { ...sampleManifest, id: "tool-2", version: "1.0.0" },
        handler: async (_input: any) => ({ result: "ok" }),
        registeredBy: "user-1",
      });

      const tools = pool.listTools();
      expect(tools).toHaveLength(2);

      const testTool = tools.find((t) => t.id === "test-tool");
      expect(testTool?.versions).toHaveLength(2);
      expect(testTool?.versions).toContain("1.0.0");
      expect(testTool?.versions).toContain("2.0.0");
    });
  });
});
