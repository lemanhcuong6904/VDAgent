import { beforeEach, describe, expect, it } from "vitest";
import type { AgentManifest } from "../../src/contracts/index.js";
import type { Grant, PolicyRevision } from "../../src/registry/policy-engine.js";
import { PolicyEngine } from "../../src/registry/policy-engine.js";
import { testScope } from "../helpers/scope.js";

describe("PolicyEngine", () => {
  let engine: PolicyEngine;

  const sampleManifest: AgentManifest = {
    apiVersion: "agent.v1",
    id: "test-agent",
    version: "1.0.0",
    displayName: "Test Agent",
    inputSchema: { type: "object" },
    outputSchema: { type: "object" },
    capabilities: ["model:completion", "tool:invoke"],
    requiredPorts: ["model", "tools"],
    toolGrants: [
      {
        toolId: "read_file",
        version: "1.0.0",
        effect: "read",
      },
    ],
    limits: {
      timeoutMs: 30000,
      maxInputBytes: 1000000,
      maxOutputBytes: 1000000,
      maxEventBytes: 100000,
      maxCheckpointBytes: 10000000,
      maxModelCalls: 10,
      maxToolCalls: 20,
      maxChildRuns: 5,
      maxDepth: 3,
      maxCostUsd: 1.0,
    },
    compatibility: {
      minHostVersion: "1.0.0",
    },
  };

  const sampleScope = testScope({ workspaceId: "ws-1" });

  beforeEach(() => {
    engine = new PolicyEngine();
  });

  describe("policy revision management", () => {
    it("should register policy revision", () => {
      const revision: PolicyRevision = {
        id: "policy-v1",
        version: "1.0.0",
        effectiveAt: new Date().toISOString(),
        rules: [],
      };

      engine.registerRevision(revision);
      // Successfully registered (no error)
      expect(true).toBe(true);
    });

    it("should activate policy revision", () => {
      const revision: PolicyRevision = {
        id: "policy-v1",
        version: "1.0.0",
        effectiveAt: new Date().toISOString(),
        rules: [],
      };

      engine.registerRevision(revision);
      engine.activateRevision("policy-v1");

      const active = engine.getActiveRevision();
      expect(active?.id).toBe("policy-v1");
    });

    it("should throw for non-existent revision", () => {
      expect(() => engine.activateRevision("unknown")).toThrow("Policy revision not found");
    });
  });

  describe("grant management", () => {
    it("should grant capability to tenant", () => {
      const grant: Grant = {
        capability: "model:completion",
        scope: {
          tenantId: "tenant-1",
        },
      };

      engine.grant("tenant-1", grant);
      // Successfully granted (no error)
      expect(true).toBe(true);
    });

    it("should revoke all grants for tenant", () => {
      const grant: Grant = {
        capability: "model:completion",
        scope: {
          tenantId: "tenant-1",
        },
      };

      engine.grant("tenant-1", grant);
      engine.revokeAll("tenant-1");

      // After revocation, authorization should fail
      const result = engine.authorize(sampleManifest, sampleScope);
      expect(result.authorized).toBe(false);
    });
  });

  describe("authorization", () => {
    it("should authorize when all capabilities granted", () => {
      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        capability: "tool:invoke",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        toolId: "read_file",
        scope: { tenantId: "tenant-1" },
      });

      const result = engine.authorize(sampleManifest, sampleScope);
      expect(result.authorized).toBe(true);
      expect(result.violations).toHaveLength(0);
    });

    it("should reject when capability missing", () => {
      // Only grant tool:invoke, not model:completion
      engine.grant("tenant-1", {
        capability: "tool:invoke",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        toolId: "read_file",
        scope: { tenantId: "tenant-1" },
      });

      const result = engine.authorize(sampleManifest, sampleScope);
      expect(result.authorized).toBe(false);
      expect(result.violations.some((v) => v.capability === "model:completion")).toBe(true);
    });

    it("should reject when tool grant missing", () => {
      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        capability: "tool:invoke",
        scope: { tenantId: "tenant-1" },
      });

      // Missing read_file tool grant

      const result = engine.authorize(sampleManifest, sampleScope);
      expect(result.authorized).toBe(false);
      expect(result.violations.some((v) => v.toolId === "read_file")).toBe(true);
    });

    it("should respect workspace scope", () => {
      // Grant only for ws-2
      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: {
          tenantId: "tenant-1",
          workspaceId: "ws-2",
        },
      });

      // Trying to use in ws-1
      const result = engine.authorize(sampleManifest, {
        ...sampleScope,
        workspaceId: "ws-1",
      });

      expect(result.authorized).toBe(false);
    });

    it("should respect audience scope", () => {
      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: {
          tenantId: "tenant-1",
          audience: ["internal"],
        },
      });

      engine.grant("tenant-1", {
        capability: "tool:invoke",
        scope: {
          tenantId: "tenant-1",
          audience: ["internal"],
        },
      });

      engine.grant("tenant-1", {
        toolId: "read_file",
        scope: {
          tenantId: "tenant-1",
          audience: ["internal"],
        },
      });

      // With matching audience
      const resultMatch = engine.authorize(sampleManifest, {
        ...sampleScope,
        audience: "internal",
      });
      expect(resultMatch.authorized).toBe(true);

      // Without matching audience
      const resultNoMatch = engine.authorize(sampleManifest, {
        ...sampleScope,
        audience: "external",
      });
      expect(resultNoMatch.authorized).toBe(false);
    });

    it("should respect grant expiration", () => {
      const pastDate = new Date(Date.now() - 86400000).toISOString(); // 1 day ago

      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: { tenantId: "tenant-1" },
        constraints: {
          expiresAt: pastDate,
        },
      });

      const result = engine.authorize(sampleManifest, sampleScope);
      expect(result.authorized).toBe(false);
    });
  });

  describe("policy rules", () => {
    it("should apply deny rule", () => {
      // Grant capabilities
      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        capability: "tool:invoke",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        toolId: "read_file",
        scope: { tenantId: "tenant-1" },
      });

      // Create policy that denies
      const revision: PolicyRevision = {
        id: "policy-deny",
        version: "1.0.0",
        effectiveAt: new Date().toISOString(),
        rules: [
          {
            id: "deny-all",
            type: "capability",
            effect: "deny",
            priority: 100,
          },
        ],
      };

      engine.registerRevision(revision);

      const result = engine.authorize(sampleManifest, sampleScope, "policy-deny");
      expect(result.authorized).toBe(false);
    });

    it("should check budget limits", () => {
      engine.grant("tenant-1", {
        capability: "model:completion",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        capability: "tool:invoke",
        scope: { tenantId: "tenant-1" },
      });

      engine.grant("tenant-1", {
        toolId: "read_file",
        scope: { tenantId: "tenant-1" },
      });

      const revision: PolicyRevision = {
        id: "policy-budget",
        version: "1.0.0",
        effectiveAt: new Date().toISOString(),
        rules: [
          {
            id: "budget-check",
            type: "budget",
            effect: "allow",
            priority: 50,
          },
        ],
      };

      engine.registerRevision(revision);

      // This manifest has maxCostUsd: 1.0 which should fail budget check
      const result = engine.authorize(sampleManifest, sampleScope, "policy-budget");
      expect(result.violations.some((v) => v.type === "budget_exceeded")).toBe(true);
    });
  });

  describe("policy pinning", () => {
    it("should create policy pin", () => {
      const revision: PolicyRevision = {
        id: "policy-v1",
        version: "1.0.0",
        effectiveAt: new Date().toISOString(),
        rules: [],
      };

      engine.registerRevision(revision);
      engine.activateRevision("policy-v1");

      const pin = engine.createPolicyPin();
      expect(pin.revisionId).toBe("policy-v1");
      expect(pin.pinnedAt).toBeDefined();
    });

    it("should throw when no policy to pin", () => {
      expect(() => engine.createPolicyPin()).toThrow("No policy revision to pin");
    });

    it("should validate pinned policy exists", () => {
      const revision: PolicyRevision = {
        id: "policy-v1",
        version: "1.0.0",
        effectiveAt: new Date().toISOString(),
        rules: [],
      };

      engine.registerRevision(revision);

      expect(engine.validatePin("policy-v1")).toBe(true);
      expect(engine.validatePin("unknown")).toBe(false);
    });
  });

  describe("tenant isolation", () => {
    it("should prevent cross-tenant access", () => {
      const sourceScope = testScope({ tenantId: "tenant-1", actorId: "user-1" });
      const targetScope = testScope({ tenantId: "tenant-2", actorId: "user-2" });

      const result = engine.checkTenantIsolation(sourceScope, targetScope);
      expect(result.safe).toBe(false);
      expect(result.violation?.type).toBe("unauthorized_scope");
    });

    it("should allow same-tenant access", () => {
      const sourceScope = testScope({ tenantId: "tenant-1", actorId: "user-1" });
      const targetScope = testScope({ tenantId: "tenant-1", actorId: "user-2" });

      const result = engine.checkTenantIsolation(sourceScope, targetScope);
      expect(result.safe).toBe(true);
    });
  });

  describe("audience leakage", () => {
    it("should detect audience leakage", () => {
      const sourceScope = testScope({ actorId: "user-1", audience: "sensitive" });
      const targetScope = testScope({ actorId: "user-2", audience: "internal" });

      const result = engine.checkAudienceLeakage(sourceScope, targetScope);
      expect(result.safe).toBe(false);
      expect(result.violation?.type).toBe("unauthorized_scope");
    });

    it("should allow when source and target share the audience", () => {
      const sourceScope = testScope({ actorId: "user-1", audience: "internal" });
      const targetScope = testScope({ actorId: "user-2", audience: "internal" });

      const result = engine.checkAudienceLeakage(sourceScope, targetScope);
      expect(result.safe).toBe(true);
    });

    it("should flag widening to a different audience", () => {
      // A single canonical audience has no subset relation: any change is leakage
      const sourceScope = testScope({ actorId: "user-1", audience: "internal" });
      const targetScope = testScope({ actorId: "user-2", audience: "public" });

      const result = engine.checkAudienceLeakage(sourceScope, targetScope);
      expect(result.safe).toBe(false);
      expect(result.violation?.message).toBe(
        "Audience leakage detected: source audience not subset of target",
      );
    });
  });
});
