/**
 * Memory Provider M8.6 Tests
 * Tests for extraction lease, redaction, resource caps, and stale cleanup
 */

import { beforeEach, describe, expect, it } from "vitest";
import { InMemoryProvider } from "../../src/session/memory-provider.js";

describe("M8.6: Extraction Lease Management", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-extraction";
  const leasedBy = "background-extractor-1";

  beforeEach(async () => {
    provider = new InMemoryProvider();
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Document for extraction",
    });
  });

  it("should acquire extraction lease", async () => {
    const result = await provider.acquireExtractionLease("doc1", workspaceId, leasedBy, 5000);

    expect(result.ok).toBe(true);
    expect(result.leaseId).toBeDefined();

    const entry = await provider.read("doc1", workspaceId);
    expect(entry?.extraction?.leaseId).toBe(result.leaseId);
    expect(entry?.extraction?.leasedBy).toBe(leasedBy);
    expect(entry?.extraction?.leasedAt).toBeDefined();
    expect(entry?.extraction?.leaseExpiresAt).toBeDefined();
  });

  it("should reject lease acquisition when lease is active", async () => {
    const first = await provider.acquireExtractionLease("doc1", workspaceId, "extractor-1", 10000);

    expect(first.ok).toBe(true);

    const second = await provider.acquireExtractionLease("doc1", workspaceId, "extractor-2", 10000);

    expect(second.ok).toBe(false);
    expect(second.reason).toContain("already leased");
  });

  it("should allow lease acquisition after expiration", async () => {
    const first = await provider.acquireExtractionLease(
      "doc1",
      workspaceId,
      leasedBy,
      50, // 50ms TTL
    );

    expect(first.ok).toBe(true);

    // Wait for lease to expire
    await new Promise((resolve) => setTimeout(resolve, 100));

    const second = await provider.acquireExtractionLease("doc1", workspaceId, "extractor-2", 5000);

    expect(second.ok).toBe(true);
    expect(second.leaseId).not.toBe(first.leaseId);
  });

  it("should release extraction lease", async () => {
    const lease = await provider.acquireExtractionLease("doc1", workspaceId, leasedBy, 5000);

    expect(lease.ok).toBe(true);

    const result = await provider.releaseExtractionLease("doc1", workspaceId, lease.leaseId!);

    expect(result.ok).toBe(true);

    const entry = await provider.read("doc1", workspaceId);
    expect(entry?.extraction?.leaseId).toBeUndefined();
    expect(entry?.extraction?.lastExtractedAt).toBeDefined();
    expect(entry?.extraction?.extractionVersion).toBe(1);
  });

  it("should reject release with wrong lease ID", async () => {
    const lease = await provider.acquireExtractionLease("doc1", workspaceId, leasedBy, 5000);

    expect(lease.ok).toBe(true);

    const result = await provider.releaseExtractionLease("doc1", workspaceId, "wrong-lease-id");

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("mismatch");
  });

  it("should increment extraction version on release", async () => {
    for (let i = 1; i <= 3; i++) {
      const lease = await provider.acquireExtractionLease("doc1", workspaceId, leasedBy, 5000);

      expect(lease.ok).toBe(true);

      await provider.releaseExtractionLease("doc1", workspaceId, lease.leaseId!);

      const entry = await provider.read("doc1", workspaceId);
      expect(entry?.extraction?.extractionVersion).toBe(i);
    }
  });
});

describe("M8.6: Stale Lease Cleanup", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-cleanup";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should clean up stale leases", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Document 1",
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Document 2",
    });

    // Acquire leases with short TTL
    await provider.acquireExtractionLease("doc1", workspaceId, "extractor", 50);
    await provider.acquireExtractionLease("doc2", workspaceId, "extractor", 50);

    // Wait for leases to expire
    await new Promise((resolve) => setTimeout(resolve, 100));

    const result = await provider.cleanupStaleLeases(workspaceId);

    expect(result.cleaned).toBe(2);

    const entry1 = await provider.read("doc1", workspaceId);
    const entry2 = await provider.read("doc2", workspaceId);

    expect(entry1?.extraction?.leaseId).toBeUndefined();
    expect(entry2?.extraction?.leaseId).toBeUndefined();
  });

  it("should not clean up active leases", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Document 1",
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Document 2",
    });

    // Acquire one stale, one active
    await provider.acquireExtractionLease("doc1", workspaceId, "extractor", 50);
    await provider.acquireExtractionLease("doc2", workspaceId, "extractor", 10000);

    await new Promise((resolve) => setTimeout(resolve, 100));

    const result = await provider.cleanupStaleLeases(workspaceId);

    expect(result.cleaned).toBe(1);

    const entry1 = await provider.read("doc1", workspaceId);
    const entry2 = await provider.read("doc2", workspaceId);

    expect(entry1?.extraction?.leaseId).toBeUndefined();
    expect(entry2?.extraction?.leaseId).toBeDefined();
  });

  it("should cleanup across all workspaces when no workspace specified", async () => {
    await provider.commit({
      workspaceId: "ws-1",
      scope: "doc1",
      content: "Document 1",
    });

    await provider.commit({
      workspaceId: "ws-2",
      scope: "doc2",
      content: "Document 2",
    });

    await provider.acquireExtractionLease("doc1", "ws-1", "extractor", 50);
    await provider.acquireExtractionLease("doc2", "ws-2", "extractor", 50);

    await new Promise((resolve) => setTimeout(resolve, 100));

    const result = await provider.cleanupStaleLeases();

    expect(result.cleaned).toBe(2);
  });
});

describe("M8.6: Redaction", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-redaction";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should redact email addresses", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Contact us at support@example.com or admin@company.org",
    });

    const entry = await provider.read("doc1", workspaceId);
    const redacted = provider.redactForExtraction(entry!);

    expect(redacted.content).toContain("[EMAIL]");
    expect(redacted.content).not.toContain("support@example.com");
    expect(redacted.content).not.toContain("admin@company.org");
  });

  it("should redact phone numbers", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Call 555-123-4567 or 555.987.6543",
    });

    const entry = await provider.read("doc1", workspaceId);
    const redacted = provider.redactForExtraction(entry!);

    expect(redacted.content).toContain("[PHONE]");
    expect(redacted.content).not.toContain("555-123-4567");
    expect(redacted.content).not.toContain("555.987.6543");
  });

  it("should redact credit card numbers", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Card: 1234-5678-9012-3456 or 1234567890123456",
    });

    const entry = await provider.read("doc1", workspaceId);
    const redacted = provider.redactForExtraction(entry!);

    expect(redacted.content).toContain("[CARD]");
    expect(redacted.content).not.toContain("1234-5678-9012-3456");
    expect(redacted.content).not.toContain("1234567890123456");
  });

  it("should redact SSN patterns", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "SSN: 123-45-6789",
    });

    const entry = await provider.read("doc1", workspaceId);
    const redacted = provider.redactForExtraction(entry!);

    expect(redacted.content).toContain("[SSN]");
    expect(redacted.content).not.toContain("123-45-6789");
  });

  it("should redact sensitive metadata fields", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Document with metadata",
      metadata: {
        api_key: "secret-key-123",
        password: "hunter2",
        auth_token: "token-abc",
        user_name: "john_doe",
      },
    });

    const entry = await provider.read("doc1", workspaceId);
    const redacted = provider.redactForExtraction(entry!);

    expect(redacted.metadata?.api_key).toBe("[REDACTED]");
    expect(redacted.metadata?.password).toBe("[REDACTED]");
    expect(redacted.metadata?.auth_token).toBe("[REDACTED]");
    expect(redacted.metadata?.user_name).toBe("john_doe"); // Not sensitive
  });

  it("should preserve non-sensitive content", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "This is normal content with no PII or sensitive data",
    });

    const entry = await provider.read("doc1", workspaceId);
    const redacted = provider.redactForExtraction(entry!);

    expect(redacted.content).toBe(entry!.content);
  });

  it("should not mutate original entry", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Email: test@example.com",
      metadata: { api_key: "secret" },
    });

    const entry = await provider.read("doc1", workspaceId);
    const originalContent = entry!.content;
    const originalMetadata = JSON.stringify(entry!.metadata);

    provider.redactForExtraction(entry!);

    // Original entry should remain unchanged
    expect(entry!.content).toBe(originalContent);
    expect(JSON.stringify(entry!.metadata)).toBe(originalMetadata);
  });
});
