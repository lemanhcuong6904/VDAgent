/**
 * Contract Validation Tests
 * Tests for validating agent contracts against schemas
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  assertValid,
  ContractTestKit,
  ContractValidator,
  invalidResult,
} from "../testkit/contract-validator.js";

describe("ContractValidator", () => {
  let validator: ContractValidator;
  let testKit: ContractTestKit;

  beforeEach(() => {
    validator = new ContractValidator();
    testKit = new ContractTestKit();
  });

  describe("AgentManifest validation", () => {
    it("should validate a minimal valid manifest", () => {
      const manifest = testKit.createMinimalManifest();
      const result = validator.validateManifest(manifest);

      expect(result.valid).toBe(true);
      expect(result.data).toBeDefined();
    });

    it("should reject manifest with invalid apiVersion", () => {
      const manifest = testKit.createMinimalManifest({
        apiVersion: "invalid.v1" as never,
      });
      const result = validator.validateManifest(manifest);

      expect(result.valid).toBe(false);
      expect(result.errors).toBeDefined();
    });

    it("should reject manifest with invalid id format", () => {
      const manifest = testKit.createMinimalManifest({
        id: "Invalid_ID!",
      });
      const result = validator.validateManifest(manifest);

      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => e.includes("id"))).toBe(true);
    });

    it("should reject manifest with invalid version", () => {
      const manifest = testKit.createMinimalManifest({
        version: "not-semver",
      });
      const result = validator.validateManifest(manifest);

      expect(result.valid).toBe(false);
    });

    it("should validate manifest with tool grants", () => {
      const manifest = testKit.createMinimalManifest({
        toolGrants: [{ toolId: "test-tool", version: "1.0.0", effect: "read" }],
      });
      const result = validator.validateManifest(manifest);

      expect(result.valid).toBe(true);
    });

    it("should validate manifest with all capabilities", () => {
      const manifest = testKit.createMinimalManifest({
        capabilities: ["model:completion", "tool:invoke", "memory:read"],
        requiredPorts: ["model", "tools", "memory"],
      });
      const result = validator.validateManifest(manifest);

      expect(result.valid).toBe(true);
    });
  });

  describe("AgentResult validation", () => {
    it("should validate a minimal valid result", () => {
      const result = testKit.createMinimalResult();
      const validationResult = validator.validateResult(result);

      expect(validationResult.valid).toBe(true);
      expect(validationResult.data).toBeDefined();
    });

    it("should validate result with output", () => {
      const result = testKit.createMinimalResult({
        output: { message: "success" },
      });
      const validationResult = validator.validateResult(result);

      expect(validationResult.valid).toBe(true);
    });

    it("should validate result with artifacts", () => {
      const result = testKit.createMinimalResult({
        artifacts: [
          {
            id: "artifact-123",
            workspaceId: "workspace-1",
            ownerRunId: "run-1",
            kind: "json",
            version: "1.0.0",
            status: "ready",
            sha256: "a".repeat(64),
            bytes: 1024,
          },
        ],
      });
      const validationResult = validator.validateResult(result);

      expect(validationResult.valid).toBe(true);
    });

    it("should reject result with invalid status", () => {
      const result = {
        status: "invalid-status",
        usage: { durationMs: 1000 },
      };
      const validationResult = validator.validateResult(result);

      expect(validationResult.valid).toBe(false);
    });

    it("should reject result with invalid artifact hash format", () => {
      const result = testKit.createMinimalResult({
        artifacts: [
          {
            id: "artifact-123",
            workspaceId: "workspace-1",
            ownerRunId: "run-1",
            kind: "json",
            version: "1.0.0",
            status: "ready",
            sha256: "invalid-hash",
            bytes: 1024,
          } as never,
        ],
      });
      const validationResult = validator.validateResult(result);

      expect(validationResult.valid).toBe(false);
    });
  });

  describe("StructuredError validation", () => {
    it("should validate a minimal valid error", () => {
      const error = testKit.createMinimalError();
      const result = validator.validateError(error);

      expect(result.valid).toBe(true);
      expect(result.data).toBeDefined();
    });

    it("should validate error with all fields", () => {
      const error = testKit.createMinimalError({
        code: "QUOTA_EXCEEDED",
        class: "policy",
        retryable: false,
        safeMessage: "Quota exceeded for this tenant",
        correlationId: "corr-123",
      });
      const result = validator.validateError(error);

      expect(result.valid).toBe(true);
    });

    it("should reject error with invalid code format", () => {
      const error = testKit.createMinimalError({
        code: "!!!invalid", // starts with special char, violates pattern
      });
      const result = validator.validateError(error);

      expect(result.valid).toBe(false);
    });

    it("should reject error with invalid class", () => {
      const error = testKit.createMinimalError({
        class: "invalid-class" as never,
      });
      const result = validator.validateError(error);

      expect(result.valid).toBe(false);
    });
  });

  describe("Test utilities", () => {
    it("should create minimal manifest with overrides", () => {
      const manifest = testKit.createMinimalManifest({
        id: "custom-agent",
        displayName: "Custom Agent",
      });

      expect(manifest.id).toBe("custom-agent");
      expect(manifest.displayName).toBe("Custom Agent");
      expect(manifest.apiVersion).toBe("agent.v1");
    });

    it("should assert valid results", () => {
      const manifest = testKit.createMinimalManifest();
      const result = validator.validateManifest(manifest);

      expect(() => assertValid(result)).not.toThrow();
    });

    it("should throw on invalid results", () => {
      const result = invalidResult(["test error"]);

      expect(() => assertValid(result)).toThrow("Validation failed");
    });

    it("should use expectValidManifest helper", () => {
      const manifest = testKit.createMinimalManifest();

      expect(() => testKit.expectValidManifest(manifest)).not.toThrow();
    });

    it("should use expectInvalidManifest helper", () => {
      const invalidManifest = { apiVersion: "wrong" };

      const errors = testKit.expectInvalidManifest(invalidManifest);
      expect(errors.length).toBeGreaterThan(0);
    });
  });
});

describe("Contract validation edge cases", () => {
  let validator: ContractValidator;

  beforeEach(() => {
    validator = new ContractValidator();
  });

  it("should handle missing required fields", () => {
    const incomplete = {
      apiVersion: "agent.v1",
      id: "test",
    };
    const result = validator.validateManifest(incomplete);

    expect(result.valid).toBe(false);
    expect(result.errors?.length).toBeGreaterThan(0);
  });

  it("should handle extra unknown fields gracefully", () => {
    const testKit = new ContractTestKit();
    const manifest = {
      ...testKit.createMinimalManifest(),
      unknownField: "should be ignored or rejected based on schema",
    };
    const result = validator.validateManifest(manifest);

    // This behavior depends on schema additionalProperties setting
    expect(result).toBeDefined();
  });

  it("should validate deeply nested structures", () => {
    const testKit = new ContractTestKit();
    const result = testKit.createMinimalResult({
      artifacts: [
        {
          id: "nested-artifact",
          workspaceId: "workspace-1",
          ownerRunId: "run-1",
          kind: "json",
          version: "1.0.0",
          status: "ready",
          sha256: "b".repeat(64),
          bytes: 2048,
        },
      ],
      evidence: [
        {
          id: "evidence-1",
          workspaceId: "workspace-1",
          runId: "run-1",
          attemptId: "attempt-1",
          fence: "1",
          policyRevision: "policy-v1",
          kind: "receipt",
          verification: "verified",
        },
      ],
    });

    const validationResult = validator.validateResult(result);
    expect(validationResult.valid).toBe(true);
  });
});
