/**
 * Memory Provider M8.3 Tests
 * Tests for resolver trust classification, encrypted credential reference, and deployment-owner approval
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  type CredentialReference,
  InMemoryProvider,
  type ResolverTrust,
} from "../../src/session/memory-provider.js";

describe("M8.3: Resolver Trust Classification", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-trust";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should register trusted resolver", async () => {
    const trust: ResolverTrust = {
      resolverType: "github-resolver",
      trustLevel: "trusted",
      approvedBy: "admin@example.com",
      approvedAt: new Date().toISOString(),
    };

    const result = await provider.registerResolverTrust("github-resolver", workspaceId, trust);

    expect(result.ok).toBe(true);

    const retrieved = await provider.getResolverTrust("github-resolver", workspaceId);
    expect(retrieved?.trustLevel).toBe("trusted");
    expect(retrieved?.approvedBy).toBe("admin@example.com");
  });

  it("should register untrusted resolver", async () => {
    const trust: ResolverTrust = {
      resolverType: "public-scraper",
      trustLevel: "untrusted",
      restrictions: ["no-credential-access", "read-only"],
    };

    await provider.registerResolverTrust("public-scraper", workspaceId, trust);

    const retrieved = await provider.getResolverTrust("public-scraper", workspaceId);
    expect(retrieved?.trustLevel).toBe("untrusted");
    expect(retrieved?.restrictions).toEqual(["no-credential-access", "read-only"]);
  });

  it("should register unknown resolver", async () => {
    const trust: ResolverTrust = {
      resolverType: "new-service",
      trustLevel: "unknown",
    };

    await provider.registerResolverTrust("new-service", workspaceId, trust);

    const retrieved = await provider.getResolverTrust("new-service", workspaceId);
    expect(retrieved?.trustLevel).toBe("unknown");
  });

  it("should update resolver trust level", async () => {
    const initialTrust: ResolverTrust = {
      resolverType: "test-resolver",
      trustLevel: "unknown",
    };

    await provider.registerResolverTrust("test-resolver", workspaceId, initialTrust);

    const updatedTrust: ResolverTrust = {
      resolverType: "test-resolver",
      trustLevel: "trusted",
      approvedBy: "security-team@example.com",
      approvedAt: new Date().toISOString(),
    };

    await provider.registerResolverTrust("test-resolver", workspaceId, updatedTrust);

    const retrieved = await provider.getResolverTrust("test-resolver", workspaceId);
    expect(retrieved?.trustLevel).toBe("trusted");
    expect(retrieved?.approvedBy).toBe("security-team@example.com");
  });

  it("should isolate resolver trust by workspace", async () => {
    const ws1Trust: ResolverTrust = {
      resolverType: "shared-resolver",
      trustLevel: "trusted",
    };

    const ws2Trust: ResolverTrust = {
      resolverType: "shared-resolver",
      trustLevel: "untrusted",
    };

    await provider.registerResolverTrust("shared-resolver", "ws-1", ws1Trust);
    await provider.registerResolverTrust("shared-resolver", "ws-2", ws2Trust);

    const ws1Retrieved = await provider.getResolverTrust("shared-resolver", "ws-1");
    const ws2Retrieved = await provider.getResolverTrust("shared-resolver", "ws-2");

    expect(ws1Retrieved?.trustLevel).toBe("trusted");
    expect(ws2Retrieved?.trustLevel).toBe("untrusted");
  });

  it("should return null for unregistered resolver", async () => {
    const retrieved = await provider.getResolverTrust("nonexistent", workspaceId);
    expect(retrieved).toBeNull();
  });

  it("should store resolver restrictions", async () => {
    const trust: ResolverTrust = {
      resolverType: "restricted-resolver",
      trustLevel: "trusted",
      approvedBy: "admin@example.com",
      restrictions: ["no-write-access", "audit-required", "data-export-forbidden"],
    };

    await provider.registerResolverTrust("restricted-resolver", workspaceId, trust);

    const retrieved = await provider.getResolverTrust("restricted-resolver", workspaceId);
    expect(retrieved?.restrictions).toHaveLength(3);
    expect(retrieved?.restrictions).toContain("audit-required");
  });
});

describe("M8.3: Encrypted Credential Reference", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-credentials";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should store encrypted credential", async () => {
    const credential: CredentialReference = {
      type: "encrypted",
      keyId: "key-12345",
      encryptedValue: "encrypted-api-key-abc123",
      metadata: {
        algorithm: "AES-256-GCM",
        keySource: "vault",
      },
    };

    const result = await provider.storeCredential("api-key", workspaceId, credential);

    expect(result.ok).toBe(true);

    const retrieved = await provider.retrieveCredential("api-key", workspaceId);
    expect(retrieved?.type).toBe("encrypted");
    expect(retrieved?.keyId).toBe("key-12345");
    expect(retrieved?.encryptedValue).toBe("encrypted-api-key-abc123");
  });

  it("should store keyring credential reference", async () => {
    const credential: CredentialReference = {
      type: "keyring",
      keyId: "system-keyring-entry-42",
      metadata: {
        service: "github-api",
        account: "bot-account",
      },
    };

    await provider.storeCredential("github-token", workspaceId, credential);

    const retrieved = await provider.retrieveCredential("github-token", workspaceId);
    expect(retrieved?.type).toBe("keyring");
    expect(retrieved?.keyId).toBe("system-keyring-entry-42");
    expect(retrieved?.metadata?.service).toBe("github-api");
  });

  it("should store vault credential reference", async () => {
    const credential: CredentialReference = {
      type: "vault",
      keyId: "vault://prod/secrets/database/password",
      metadata: {
        vaultUrl: "https://vault.example.com",
        role: "app-reader",
      },
    };

    await provider.storeCredential("db-password", workspaceId, credential);

    const retrieved = await provider.retrieveCredential("db-password", workspaceId);
    expect(retrieved?.type).toBe("vault");
    expect(retrieved?.keyId).toContain("vault://");
  });

  it("should isolate credentials by workspace", async () => {
    const ws1Credential: CredentialReference = {
      type: "encrypted",
      keyId: "ws1-key",
      encryptedValue: "ws1-encrypted-value",
    };

    const ws2Credential: CredentialReference = {
      type: "encrypted",
      keyId: "ws2-key",
      encryptedValue: "ws2-encrypted-value",
    };

    await provider.storeCredential("shared-key", "ws-1", ws1Credential);
    await provider.storeCredential("shared-key", "ws-2", ws2Credential);

    const ws1Retrieved = await provider.retrieveCredential("shared-key", "ws-1");
    const ws2Retrieved = await provider.retrieveCredential("shared-key", "ws-2");

    expect(ws1Retrieved?.keyId).toBe("ws1-key");
    expect(ws2Retrieved?.keyId).toBe("ws2-key");
  });

  it("should return null for nonexistent credential", async () => {
    const retrieved = await provider.retrieveCredential("nonexistent", workspaceId);
    expect(retrieved).toBeNull();
  });

  it("should update credential reference", async () => {
    const initialCredential: CredentialReference = {
      type: "encrypted",
      keyId: "old-key",
      encryptedValue: "old-value",
    };

    await provider.storeCredential("rotated-key", workspaceId, initialCredential);

    const newCredential: CredentialReference = {
      type: "encrypted",
      keyId: "new-key",
      encryptedValue: "new-value",
      metadata: { rotatedAt: new Date().toISOString() },
    };

    await provider.storeCredential("rotated-key", workspaceId, newCredential);

    const retrieved = await provider.retrieveCredential("rotated-key", workspaceId);
    expect(retrieved?.keyId).toBe("new-key");
    expect(retrieved?.metadata?.rotatedAt).toBeDefined();
  });

  it("should store credential metadata", async () => {
    const credential: CredentialReference = {
      type: "encrypted",
      keyId: "meta-key",
      encryptedValue: "encrypted",
      metadata: {
        createdAt: "2026-01-15T00:00:00Z",
        expiresAt: "2027-01-15T00:00:00Z",
        owner: "security-team",
        scope: "production",
        tags: ["critical", "rotated-monthly"],
      },
    };

    await provider.storeCredential("meta-test", workspaceId, credential);

    const retrieved = await provider.retrieveCredential("meta-test", workspaceId);
    expect(retrieved?.metadata?.owner).toBe("security-team");
    expect(retrieved?.metadata?.tags).toContain("critical");
  });
});

describe("M8.3: Deployment-Owner Approval", () => {
  let provider: InMemoryProvider;

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should request credential access approval", async () => {
    const approval = await provider.requestApproval({
      operation: "credential_access",
      resource: "production-api-key",
      requestedBy: "agent-worker-1",
    });

    expect(approval.id).toBeDefined();
    expect(approval.operation).toBe("credential_access");
    expect(approval.status).toBe("pending");
    expect(approval.requestedAt).toBeDefined();
  });

  it("should request resolver use approval", async () => {
    const approval = await provider.requestApproval({
      operation: "resolver_use",
      resource: "external-data-source",
      requestedBy: "background-job-2",
    });

    expect(approval.operation).toBe("resolver_use");
    expect(approval.status).toBe("pending");
  });

  it("should request export approval", async () => {
    const approval = await provider.requestApproval({
      operation: "export",
      resource: "workspace-memories",
      requestedBy: "admin-tool",
    });

    expect(approval.operation).toBe("export");
    expect(approval.status).toBe("pending");
  });

  it("should request delete approval", async () => {
    const approval = await provider.requestApproval({
      operation: "delete",
      resource: "sensitive-data",
      requestedBy: "cleanup-service",
    });

    expect(approval.operation).toBe("delete");
    expect(approval.status).toBe("pending");
  });

  it("should approve pending request", async () => {
    const approval = await provider.requestApproval({
      operation: "credential_access",
      resource: "api-key",
      requestedBy: "agent",
    });

    const result = await provider.processApproval(
      approval.id,
      "approved",
      "security-admin@example.com",
      "Verified legitimate access need",
    );

    expect(result.ok).toBe(true);

    const updated = await provider.getApprovalRequest(approval.id);
    expect(updated?.status).toBe("approved");
    expect(updated?.approvedBy).toBe("security-admin@example.com");
    expect(updated?.approvedAt).toBeDefined();
    expect(updated?.reason).toBe("Verified legitimate access need");
  });

  it("should deny pending request", async () => {
    const approval = await provider.requestApproval({
      operation: "export",
      resource: "confidential-data",
      requestedBy: "untrusted-agent",
    });

    const result = await provider.processApproval(
      approval.id,
      "denied",
      "compliance-officer@example.com",
      "Insufficient permissions",
    );

    expect(result.ok).toBe(true);

    const updated = await provider.getApprovalRequest(approval.id);
    expect(updated?.status).toBe("denied");
    expect(updated?.approvedBy).toBe("compliance-officer@example.com");
    expect(updated?.reason).toBe("Insufficient permissions");
  });

  it("should reject approval of already processed request", async () => {
    const approval = await provider.requestApproval({
      operation: "delete",
      resource: "test-data",
      requestedBy: "agent",
    });

    await provider.processApproval(approval.id, "approved", "admin@example.com");

    const result = await provider.processApproval(approval.id, "denied", "other-admin@example.com");

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("already");
  });

  it("should reject approval of nonexistent request", async () => {
    const result = await provider.processApproval(
      "nonexistent-id",
      "approved",
      "admin@example.com",
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("not found");
  });

  it("should retrieve approval request", async () => {
    const approval = await provider.requestApproval({
      operation: "resolver_use",
      resource: "external-api",
      requestedBy: "integration-service",
    });

    const retrieved = await provider.getApprovalRequest(approval.id);

    expect(retrieved).not.toBeNull();
    expect(retrieved?.id).toBe(approval.id);
    expect(retrieved?.operation).toBe("resolver_use");
    expect(retrieved?.resource).toBe("external-api");
  });

  it("should return null for nonexistent approval request", async () => {
    const retrieved = await provider.getApprovalRequest("nonexistent");
    expect(retrieved).toBeNull();
  });
});

describe("M8.3: Integration - Trust + Approval Workflow", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-integration";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should require approval before accessing untrusted resolver", async () => {
    // Register untrusted resolver
    const trust: ResolverTrust = {
      resolverType: "new-external-service",
      trustLevel: "untrusted",
      restrictions: ["requires-approval"],
    };

    await provider.registerResolverTrust("new-external-service", workspaceId, trust);

    // Request approval
    const approval = await provider.requestApproval({
      operation: "resolver_use",
      resource: "new-external-service",
      requestedBy: "agent-123",
    });

    expect(approval.status).toBe("pending");

    // Verify trust level requires approval
    const retrievedTrust = await provider.getResolverTrust("new-external-service", workspaceId);
    expect(retrievedTrust?.trustLevel).toBe("untrusted");
    expect(retrievedTrust?.restrictions).toContain("requires-approval");
  });

  it("should allow trusted resolver without approval", async () => {
    const trust: ResolverTrust = {
      resolverType: "internal-api",
      trustLevel: "trusted",
      approvedBy: "platform-team@example.com",
      approvedAt: new Date().toISOString(),
    };

    await provider.registerResolverTrust("internal-api", workspaceId, trust);

    const retrievedTrust = await provider.getResolverTrust("internal-api", workspaceId);
    expect(retrievedTrust?.trustLevel).toBe("trusted");
    expect(retrievedTrust?.approvedBy).toBeDefined();
  });

  it("should require approval for credential access from untrusted context", async () => {
    // Store credential
    const credential: CredentialReference = {
      type: "encrypted",
      keyId: "prod-key",
      encryptedValue: "encrypted-value",
    };

    await provider.storeCredential("production-secret", workspaceId, credential);

    // Request approval for access
    const approval = await provider.requestApproval({
      operation: "credential_access",
      resource: "production-secret",
      requestedBy: "new-agent",
    });

    expect(approval.status).toBe("pending");

    // Approval required before credential can be safely used
    const result = await provider.processApproval(
      approval.id,
      "approved",
      "security-team@example.com",
    );

    expect(result.ok).toBe(true);

    // Now credential can be accessed
    const retrievedCredential = await provider.retrieveCredential("production-secret", workspaceId);
    expect(retrievedCredential).not.toBeNull();
  });

  it("should audit resolver trust changes", async () => {
    const initialTrust: ResolverTrust = {
      resolverType: "audited-resolver",
      trustLevel: "unknown",
    };

    await provider.registerResolverTrust("audited-resolver", workspaceId, initialTrust);

    // Upgrade to trusted
    const upgradedTrust: ResolverTrust = {
      resolverType: "audited-resolver",
      trustLevel: "trusted",
      approvedBy: "security-admin@example.com",
      approvedAt: new Date().toISOString(),
    };

    await provider.registerResolverTrust("audited-resolver", workspaceId, upgradedTrust);

    // Record audit entry
    await provider.recordAudit({
      workspaceId,
      operation: "edit",
      actor: "security-admin@example.com",
      resource: "audited-resolver",
      details: {
        trustLevel: { from: "unknown", to: "trusted" },
      },
      success: true,
    });

    const auditLog = await provider.queryAudit(workspaceId, {
      operation: "edit",
      resource: "audited-resolver",
    });

    expect(auditLog).toHaveLength(1);
    expect(auditLog[0].details?.trustLevel).toEqual({ from: "unknown", to: "trusted" });
  });
});

it("filters audit resource within workspace before applying result limit", async () => {
  const provider = new InMemoryProvider();
  for (const [workspaceId, resource] of [
    ["one", "target"],
    ["one", "other"],
    ["two", "target"],
  ]) {
    await provider.recordAudit({
      workspaceId,
      resource,
      actor: "operator",
      operation: "edit",
      success: true,
    });
  }
  const results = await provider.queryAudit("one", { resource: "target", limit: 1 });
  expect(results).toHaveLength(1);
  expect(results[0]).toMatchObject({ workspaceId: "one", resource: "target" });
  expect(await provider.queryAudit("one", { resource: "absent" })).toEqual([]);
});
