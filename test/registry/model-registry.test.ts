import { beforeEach, describe, expect, it } from "vitest";
import type { ModelProvider } from "../../src/registry/model-registry.js";
import { defaultProfiles, ModelRegistry } from "../../src/registry/model-registry.js";

describe("ModelRegistry", () => {
  let registry: ModelRegistry;

  beforeEach(() => {
    registry = new ModelRegistry();
  });

  describe("profile management", () => {
    it("should register model profile", () => {
      const profile = defaultProfiles[0];
      registry.registerProfile(profile);

      const retrieved = registry.getProfile(profile.id);
      expect(retrieved).toEqual(profile);
    });

    it("should list all profiles", () => {
      defaultProfiles.forEach((p) => {
        registry.registerProfile(p);
      });

      const profiles = registry.listProfiles();
      expect(profiles).toHaveLength(defaultProfiles.length);
    });

    it("should list profiles by provider", () => {
      defaultProfiles.forEach((p) => {
        registry.registerProfile(p);
      });

      const anthropicProfiles = registry.listByProvider("anthropic");
      expect(anthropicProfiles).toHaveLength(3);
      expect(anthropicProfiles.every((p) => p.provider === "anthropic")).toBe(true);
    });
  });

  describe("provider management", () => {
    it("should register provider adapter", () => {
      const mockProvider: ModelProvider = {
        name: "test-provider",
        complete: async () => ({
          content: "test response",
          usage: { inputTokens: 10, outputTokens: 20 },
          finishReason: "stop",
          requestId: "req-123",
        }),
      };

      registry.registerProvider(mockProvider);
      // Provider registered successfully (no error thrown)
      expect(true).toBe(true);
    });
  });

  describe("model port creation", () => {
    beforeEach(() => {
      defaultProfiles.forEach((p) => {
        registry.registerProfile(p);
      });

      const mockProvider: ModelProvider = {
        name: "anthropic",
        complete: async (params) => ({
          content: `Response to: ${params.messages[0].content}`,
          usage: {
            inputTokens: 100,
            outputTokens: 50,
            cacheReadTokens: 10,
            cacheWriteTokens: 5,
          },
          finishReason: "stop",
          requestId: "req-456",
        }),
      };

      registry.registerProvider(mockProvider);
    });

    it("should create model port with usage tracking", async () => {
      const port = registry.createModelPort("run-1", "attempt-1");

      const result = await port.complete({
        messages: [{ role: "user", content: "Hello" }],
        model: "claude-3-5-sonnet-20241022",
      });

      expect(result.content).toContain("Hello");
      expect(result.usage.inputTokens).toBe(100);
      expect(result.usage.outputTokens).toBe(50);
    });

    it("should track usage in ledger", async () => {
      const port = registry.createModelPort("run-1", "attempt-1");

      await port.complete({
        messages: [{ role: "user", content: "Hello" }],
        model: "claude-3-5-sonnet-20241022",
      });

      const usage = registry.getRunUsage("run-1");
      expect(usage).toHaveLength(1);
      expect(usage[0].modelId).toBe("claude-3-5-sonnet-20241022");
      expect(usage[0].runId).toBe("run-1");
    });

    it("should calculate cost correctly", async () => {
      const port = registry.createModelPort("run-1", "attempt-1");

      await port.complete({
        messages: [{ role: "user", content: "Hello" }],
        model: "claude-3-5-sonnet-20241022",
      });

      const totalCost = registry.getRunCost("run-1");

      // Expected: (100/1000)*0.003 + (50/1000)*0.015 + (10/1000)*0.0003 + (5/1000)*0.00375
      // = 0.0003 + 0.00075 + 0.000003 + 0.00001875
      // = 0.00107175
      expect(totalCost).toBeCloseTo(0.00107175, 8);
    });

    it("should throw for unknown model", async () => {
      const port = registry.createModelPort("run-1", "attempt-1");

      await expect(
        port.complete({
          messages: [{ role: "user", content: "Hello" }],
          model: "unknown-model",
        }),
      ).rejects.toThrow("Model profile not found");
    });

    it("should throw for unknown provider", async () => {
      registry.registerProfile({
        id: "test-model",
        name: "Test Model",
        provider: "unknown-provider",
        contextWindow: 100000,
        maxOutputTokens: 4096,
        supportsFunctions: false,
        supportsVision: false,
        costPer1kInput: 0.001,
        costPer1kOutput: 0.002,
      });

      const port = registry.createModelPort("run-1", "attempt-1");

      await expect(
        port.complete({
          messages: [{ role: "user", content: "Hello" }],
          model: "test-model",
        }),
      ).rejects.toThrow("Provider not found");
    });
  });

  describe("schema validation", () => {
    it("should validate object schema", () => {
      const result = registry.validateSchemaOutput(
        { name: "John", age: 30 },
        {
          type: "object",
          required: ["name", "age"],
        },
      );

      expect(result.valid).toBe(true);
    });

    it("should reject missing required fields", () => {
      const result = registry.validateSchemaOutput(
        { name: "John" },
        {
          type: "object",
          required: ["name", "age"],
        },
      );

      expect(result.valid).toBe(false);
      expect(result.errors).toContain("Missing required field: age");
    });

    it("should reject wrong type", () => {
      const result = registry.validateSchemaOutput("not an object", { type: "object" });

      expect(result.valid).toBe(false);
      expect(result.errors).toContain("Output must be an object");
    });

    it("should validate array schema", () => {
      const result = registry.validateSchemaOutput([1, 2, 3], { type: "array" });

      expect(result.valid).toBe(true);
    });

    it("should reject non-array for array schema", () => {
      const result = registry.validateSchemaOutput({ items: [1, 2, 3] }, { type: "array" });

      expect(result.valid).toBe(false);
      expect(result.errors).toContain("Output must be an array");
    });

    it("should pass when no schema provided", () => {
      const result = registry.validateSchemaOutput({ anything: true }, undefined);

      expect(result.valid).toBe(true);
    });
  });

  describe("deadline checking", () => {
    it("should return true for future deadline", () => {
      const futureDeadline = Date.now() + 60000; // 1 minute from now
      expect(registry.checkDeadline(futureDeadline)).toBe(true);
    });

    it("should return false for past deadline", () => {
      const pastDeadline = Date.now() - 1000; // 1 second ago
      expect(registry.checkDeadline(pastDeadline)).toBe(false);
    });
  });

  describe("statistics", () => {
    beforeEach(() => {
      defaultProfiles.forEach((p) => {
        registry.registerProfile(p);
      });

      const mockProvider: ModelProvider = {
        name: "anthropic",
        complete: async () => {
          // Add small delay to ensure measurable duration
          await new Promise((resolve) => setTimeout(resolve, 10));
          return {
            content: "response",
            usage: {
              inputTokens: 100,
              outputTokens: 50,
            },
            finishReason: "stop",
            requestId: "req-123",
          };
        },
      };

      registry.registerProvider(mockProvider);
    });

    it("should compute overall statistics", async () => {
      const port1 = registry.createModelPort("run-1", "attempt-1");
      const port2 = registry.createModelPort("run-2", "attempt-1");

      await port1.complete({
        messages: [{ role: "user", content: "Hello" }],
        model: "claude-3-5-sonnet-20241022",
      });

      await port2.complete({
        messages: [{ role: "user", content: "World" }],
        model: "claude-3-5-haiku-20241022",
      });

      const stats = registry.getStatistics();

      expect(stats.totalCalls).toBe(2);
      expect(stats.totalInputTokens).toBe(200);
      expect(stats.totalOutputTokens).toBe(100);
      expect(stats.totalCost).toBeGreaterThan(0);
    });

    it("should filter statistics by provider", async () => {
      const port = registry.createModelPort("run-1", "attempt-1");

      await port.complete({
        messages: [{ role: "user", content: "Hello" }],
        model: "claude-3-5-sonnet-20241022",
      });

      const stats = registry.getStatistics({ provider: "anthropic" });

      expect(stats.totalCalls).toBe(1);
    });

    it("should filter statistics by model", async () => {
      const port = registry.createModelPort("run-1", "attempt-1");

      await port.complete({
        messages: [{ role: "user", content: "Hello" }],
        model: "claude-3-5-sonnet-20241022",
      });

      const stats = registry.getStatistics({ modelId: "claude-3-5-sonnet-20241022" });

      expect(stats.totalCalls).toBe(1);
      expect(stats.averageDuration).toBeGreaterThan(0);
    });

    it("should return zero statistics for no matching usage", () => {
      const stats = registry.getStatistics({ provider: "nonexistent" });

      expect(stats.totalCalls).toBe(0);
      expect(stats.totalInputTokens).toBe(0);
      expect(stats.totalOutputTokens).toBe(0);
      expect(stats.totalCost).toBe(0);
      expect(stats.averageDuration).toBe(0);
    });
  });
});
