import { beforeEach, describe, expect, it } from "vitest";
import type { AgentManifest } from "../../src/contracts/index.js";
import { AgentRegistry } from "../../src/registry/agent-registry.js";

describe("AgentRegistry", () => {
  let registry: AgentRegistry;

  const sampleManifest: AgentManifest = {
    apiVersion: "agent.v1",
    id: "test-agent",
    version: "1.0.0",
    displayName: "Test Agent",
    inputSchema: { type: "object" },
    outputSchema: { type: "object" },
    capabilities: ["model:completion"],
    requiredPorts: ["model"],
    toolGrants: [],
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

  beforeEach(() => {
    registry = new AgentRegistry();
  });

  describe("register", () => {
    it("should register a new agent version", async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "pending",
        registeredBy: "user-1",
      });

      const registration = registry.getRegistration("test-agent", "1.0.0");
      expect(registration).toBeDefined();
      expect(registration?.version).toBe("1.0.0");
      expect(registration?.activationState).toBe("pending");
    });

    it("should reject invalid manifest", async () => {
      const invalidManifest = { ...sampleManifest };
      delete (invalidManifest as any).apiVersion;

      await expect(
        registry.register({
          id: "test-agent",
          version: "1.0.0",
          manifest: invalidManifest as AgentManifest,
          activationState: "pending",
          registeredBy: "user-1",
        }),
      ).rejects.toThrow("Invalid manifest");
    });

    it("should reject invalid version format", async () => {
      await expect(
        registry.register({
          id: "test-agent",
          version: "invalid",
          manifest: sampleManifest,
          activationState: "pending",
          registeredBy: "user-1",
        }),
      ).rejects.toThrow("Invalid version format");
    });

    it("should auto-enable first version if state is enabled", async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "enabled",
        registeredBy: "user-1",
      });

      const activeVersion = registry.getActiveVersion("test-agent");
      expect(activeVersion).toBe("1.0.0");
    });
  });

  describe("updateActivation", () => {
    beforeEach(async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "pending",
        registeredBy: "user-1",
      });
    });

    it("should update activation state to enabled", async () => {
      await registry.updateActivation("test-agent", "1.0.0", "enabled");

      const registration = registry.getRegistration("test-agent", "1.0.0");
      expect(registration?.activationState).toBe("enabled");
      expect(registry.getActiveVersion("test-agent")).toBe("1.0.0");
    });

    it("should set canary percentage", async () => {
      await registry.updateActivation("test-agent", "1.0.0", "canary", {
        canaryPercentage: 20,
      });

      const registration = registry.getRegistration("test-agent", "1.0.0");
      expect(registration?.activationState).toBe("canary");
      expect(registration?.canaryPercentage).toBe(20);
    });

    it("should set allowlist", async () => {
      await registry.updateActivation("test-agent", "1.0.0", "canary", {
        allowlist: ["user-1", "user-2"],
      });

      const registration = registry.getRegistration("test-agent", "1.0.0");
      expect(registration?.allowlist).toEqual(["user-1", "user-2"]);
    });

    it("should throw for non-existent agent", async () => {
      await expect(registry.updateActivation("unknown", "1.0.0", "enabled")).rejects.toThrow(
        "Agent unknown@1.0.0 not found",
      );
    });
  });

  describe("canary rollout", () => {
    beforeEach(async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "enabled",
        registeredBy: "user-1",
      });

      await registry.register({
        id: "test-agent",
        version: "1.1.0",
        manifest: sampleManifest,
        activationState: "pending",
        registeredBy: "user-1",
      });

      await registry.updateActivation("test-agent", "1.1.0", "canary", {
        canaryPercentage: 50,
      });
    });

    it("should check allowlist membership", async () => {
      await registry.updateActivation("test-agent", "1.1.0", "canary", {
        allowlist: ["user-1"],
      });

      const inAllowlist = registry.isInCanaryAllowlist("test-agent", "1.1.0", "user-1");
      expect(inAllowlist).toBe(true);

      const notInAllowlist = registry.isInCanaryAllowlist("test-agent", "1.1.0", "user-999");
      expect(notInAllowlist).toBe(false);
    });

    it("should resolve canary version for allowlisted user", () => {
      const registration = registry.getRegistration("test-agent", "1.1.0");
      if (registration) {
        registration.allowlist = ["user-1"];
      }

      const version = registry.resolveVersion("test-agent", "user-1");
      expect(version).toBe("1.1.0");
    });

    it("should resolve active version for non-canary user", () => {
      const version = registry.resolveVersion("test-agent", "user-999");
      // User-999 might or might not be in the 50% canary, but active should exist
      expect(["1.0.0", "1.1.0"]).toContain(version);
    });
  });

  describe("version pin", () => {
    it("should create version pin", () => {
      const pin = registry.createVersionPin("test-agent", "1.0.0", "policy-v1");

      expect(pin.agentId).toBe("test-agent");
      expect(pin.version).toBe("1.0.0");
      expect(pin.policyRevision).toBe("policy-v1");
      expect(pin.pinnedAt).toBeDefined();
    });
  });

  describe("health check", () => {
    it("should pass health check for valid agent", async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "enabled",
        registeredBy: "user-1",
      });

      const health = await registry.healthCheck("test-agent", "1.0.0");
      expect(health.healthy).toBe(true);
      expect(health.errors).toHaveLength(0);
    });

    it("should fail health check for disabled agent", async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "disabled",
        registeredBy: "user-1",
      });

      const health = await registry.healthCheck("test-agent", "1.0.0");
      expect(health.healthy).toBe(false);
      expect(health.errors).toContain("Agent is disabled");
    });

    it("should fail health check for non-existent agent", async () => {
      const health = await registry.healthCheck("unknown", "1.0.0");
      expect(health.healthy).toBe(false);
      expect(health.errors).toContain("Agent not found");
    });
  });

  describe("rollback", () => {
    it("should rollback to previous version", async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "enabled",
        registeredBy: "user-1",
      });

      // Small delay to ensure different timestamps
      await new Promise((resolve) => setTimeout(resolve, 10));

      await registry.register({
        id: "test-agent",
        version: "1.1.0",
        manifest: sampleManifest,
        activationState: "pending",
        registeredBy: "user-1",
      });

      // Activate the new version first
      await registry.updateActivation("test-agent", "1.1.0", "enabled");
      expect(registry.getActiveVersion("test-agent")).toBe("1.1.0");

      // Now rollback to previous
      const rolledBackVersion = await registry.rollback("test-agent");
      expect(rolledBackVersion).toBe("1.0.0");
      expect(registry.getActiveVersion("test-agent")).toBe("1.0.0");
    });

    it("should return undefined if no previous version", async () => {
      await registry.register({
        id: "test-agent",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "enabled",
        registeredBy: "user-1",
      });

      const rolledBackVersion = await registry.rollback("test-agent");
      expect(rolledBackVersion).toBeUndefined();
    });
  });

  describe("list operations", () => {
    beforeEach(async () => {
      await registry.register({
        id: "agent-1",
        version: "1.0.0",
        manifest: sampleManifest,
        activationState: "enabled",
        registeredBy: "user-1",
      });

      await registry.register({
        id: "agent-1",
        version: "1.1.0",
        manifest: sampleManifest,
        activationState: "pending",
        registeredBy: "user-1",
      });

      await registry.register({
        id: "agent-2",
        version: "1.0.0",
        manifest: { ...sampleManifest, id: "agent-2" },
        activationState: "enabled",
        registeredBy: "user-1",
      });
    });

    it("should list all versions of an agent", () => {
      const versions = registry.listVersions("agent-1");
      expect(versions).toHaveLength(2);
      expect(versions.map((v) => v.version)).toContain("1.0.0");
      expect(versions.map((v) => v.version)).toContain("1.1.0");
    });

    it("should list all agents", () => {
      const agents = registry.listAgents();
      expect(agents).toHaveLength(2);

      const agent1 = agents.find((a) => a.id === "agent-1");
      expect(agent1?.versions).toBe(2);
      expect(agent1?.activeVersion).toBe("1.0.0");

      const agent2 = agents.find((a) => a.id === "agent-2");
      expect(agent2?.versions).toBe(1);
      expect(agent2?.activeVersion).toBe("1.0.0");
    });
  });
});
