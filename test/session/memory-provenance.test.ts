/**
 * Memory Provider M8.5 Tests
 * Tests for retrieval filter-before-rank, provenance, temporal cutoff, bounded hybrid search
 */

import { beforeEach, describe, expect, it } from "vitest";
import { InMemoryProvider } from "../../src/session/memory-provider.js";

describe("M8.5: Provenance Filtering", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-provenance";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should filter by single provenance source", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Content from GitHub API",
      provenance: { source: "github-api", trustLevel: "trusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Content from web scraper",
      provenance: { source: "web-scraper", trustLevel: "untrusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc3",
      content: "Content from database",
      provenance: { source: "database", trustLevel: "trusted" },
    });

    const results = await provider.search("Content", workspaceId, {
      provenance: { sources: ["github-api"] },
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.provenance?.source).toBe("github-api");
  });

  it("should filter by multiple provenance sources", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "API content",
      provenance: { source: "github-api" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Database content",
      provenance: { source: "database" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc3",
      content: "Scraper content",
      provenance: { source: "web-scraper" },
    });

    const results = await provider.search("content", workspaceId, {
      provenance: { sources: ["github-api", "database"] },
    });

    expect(results).toHaveLength(2);
    expect(results.map((r) => r.entry.provenance?.source).sort()).toEqual([
      "database",
      "github-api",
    ]);
  });

  it("should filter by trust level", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Trusted source data",
      provenance: { source: "internal-api", trustLevel: "trusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Untrusted source data",
      provenance: { source: "public-web", trustLevel: "untrusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc3",
      content: "Unknown source data",
      provenance: { source: "legacy", trustLevel: "unknown" },
    });

    const trustedResults = await provider.search("data", workspaceId, {
      provenance: { trustLevels: ["trusted"] },
    });

    expect(trustedResults).toHaveLength(1);
    expect(trustedResults[0].entry.provenance?.trustLevel).toBe("trusted");

    const untrustedResults = await provider.search("data", workspaceId, {
      provenance: { trustLevels: ["untrusted", "unknown"] },
    });

    expect(untrustedResults).toHaveLength(2);
  });

  it("should exclude entries without provenance when filtering", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Data with provenance",
      provenance: { source: "api" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Data without provenance",
    });

    const results = await provider.search("Data", workspaceId, {
      provenance: { sources: ["api"] },
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.provenance?.source).toBe("api");
  });

  it("should combine source and trust level filters", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "API trusted content",
      provenance: { source: "api", trustLevel: "trusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "API untrusted content",
      provenance: { source: "api", trustLevel: "untrusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc3",
      content: "DB trusted content",
      provenance: { source: "db", trustLevel: "trusted" },
    });

    const results = await provider.search("content", workspaceId, {
      provenance: {
        sources: ["api"],
        trustLevels: ["trusted"],
      },
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.provenance?.source).toBe("api");
    expect(results[0].entry.provenance?.trustLevel).toBe("trusted");
  });
});

describe("M8.5: Temporal Cutoff", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-temporal";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should return entries as of a specific timestamp", async () => {
    const v1Result = await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Version 1",
    });

    await new Promise((resolve) => setTimeout(resolve, 100));

    const v2Result = await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Version 2",
    });

    // Set asOf to be exactly midway between V1 and V2
    const v1Time = Date.parse(v1Result.entry!.createdAt);
    const v2Time = Date.parse(v2Result.entry!.createdAt);
    const asOf = new Date((v1Time + v2Time) / 2).toISOString();

    const results = await provider.search("Version", workspaceId, {
      asOf,
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.content).toBe("Version 1");
    expect(results[0].entry.revision).toBe(1);
  });

  it("should exclude entries created after asOf timestamp", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Early entry",
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const asOf = new Date().toISOString();

    await new Promise((resolve) => setTimeout(resolve, 50));

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Late entry",
    });

    const results = await provider.search("entry", workspaceId, {
      asOf,
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.content).toBe("Early entry");
  });

  it("should exclude expired entries by default", async () => {
    const now = Date.now();
    const past = new Date(now - 10000).toISOString();

    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Expired content",
      retention: { expiresAt: past },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Valid content",
    });

    const results = await provider.search("content", workspaceId);

    expect(results).toHaveLength(1);
    expect(results[0].entry.content).toBe("Valid content");
  });

  it("should include expired entries when requested", async () => {
    const now = Date.now();
    const past = new Date(now - 10000).toISOString();

    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Expired content",
      retention: { expiresAt: past },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "Valid content",
    });

    const results = await provider.search("content", workspaceId, {
      includeExpired: true,
    });

    expect(results).toHaveLength(2);
  });

  it("should handle createdAfter filter", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Old entry",
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const cutoff = new Date().toISOString();

    await new Promise((resolve) => setTimeout(resolve, 50));

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "New entry",
    });

    const results = await provider.search("entry", workspaceId, {
      createdAfter: cutoff,
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.content).toBe("New entry");
  });

  it("should handle createdBefore filter", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Old entry",
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const cutoff = new Date().toISOString();

    await new Promise((resolve) => setTimeout(resolve, 50));

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "New entry",
    });

    const results = await provider.search("entry", workspaceId, {
      createdBefore: cutoff,
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.content).toBe("Old entry");
  });
});

describe("M8.5: Bounded Hybrid Search", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-hybrid";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should limit candidates before ranking", async () => {
    // Create 100 entries
    for (let i = 0; i < 100; i++) {
      await provider.commit({
        workspaceId,
        scope: `doc${i}`,
        content: `Document ${i} contains searchable text`,
      });
    }

    const results = await provider.search("searchable", workspaceId, {
      hybrid: { maxCandidates: 10 },
      limit: 5,
    });

    expect(results.length).toBeLessThanOrEqual(5);
  });

  it("should score with phrase weight", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "machine learning model",
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "machine learning machine learning",
    });

    const results = await provider.search("machine learning", workspaceId, {
      hybrid: { phraseWeight: 2, termWeight: 0 },
    });

    expect(results).toHaveLength(2);
    expect(results[0].entry.scope).toBe("doc2"); // More phrase matches
  });

  it("should score with term weight", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "deep learning neural networks",
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "deep learning",
    });

    const results = await provider.search("deep learning networks", workspaceId, {
      hybrid: { phraseWeight: 0, termWeight: 1 },
      limit: 10,
    });

    expect(results.length).toBeGreaterThan(0);
    // doc1 has all three terms individually
    expect(results.some((r) => r.entry.scope === "doc1")).toBe(true);
  });

  it("should respect maxScanChars", async () => {
    const longContent = `prefix ${"x".repeat(10000)} needle`;

    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: longContent,
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "needle at start",
    });

    const results = await provider.search("needle", workspaceId, {
      hybrid: { maxScanChars: 100 },
    });

    // doc2 should score higher since needle is within scan window
    expect(results[0].entry.scope).toBe("doc2");
  });

  it("should combine phrase and term weights", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "machine learning is a subset of artificial intelligence",
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "machine learning machine learning",
    });

    const results = await provider.search("machine learning intelligence", workspaceId, {
      hybrid: { phraseWeight: 1, termWeight: 0.5 },
    });

    expect(results).toHaveLength(2);
    // Both should score but doc2 has more phrase matches
  });

  it("should return empty for non-matching query", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "Some content here",
    });

    const results = await provider.search("nonexistent", workspaceId);

    expect(results).toHaveLength(0);
  });
});

describe("M8.5: Integration - Filter Before Rank", () => {
  let provider: InMemoryProvider;
  const workspaceId = "ws-integration";

  beforeEach(() => {
    provider = new InMemoryProvider();
  });

  it("should apply provenance filter before scoring", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "query query query query", // High score
      provenance: { source: "untrusted", trustLevel: "untrusted" },
    });

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "query", // Low score
      provenance: { source: "trusted", trustLevel: "trusted" },
    });

    const results = await provider.search("query", workspaceId, {
      provenance: { trustLevels: ["trusted"] },
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.scope).toBe("doc2");
  });

  it("should apply temporal cutoff before scoring", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "important query query query",
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const asOf = new Date().toISOString();

    await new Promise((resolve) => setTimeout(resolve, 50));

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "query query query query query", // Higher score
    });

    const results = await provider.search("query", workspaceId, {
      asOf,
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.scope).toBe("doc1");
  });

  it("should combine all filters with bounded search", async () => {
    await provider.commit({
      workspaceId,
      scope: "doc1",
      content: "trusted early data",
      provenance: { source: "api", trustLevel: "trusted" },
      audience: "user",
    });

    await new Promise((resolve) => setTimeout(resolve, 50));

    const asOf = new Date().toISOString();

    await new Promise((resolve) => setTimeout(resolve, 50));

    await provider.commit({
      workspaceId,
      scope: "doc2",
      content: "trusted late data",
      provenance: { source: "api", trustLevel: "trusted" },
      audience: "user",
    });

    await provider.commit({
      workspaceId,
      scope: "doc3",
      content: "untrusted early data",
      provenance: { source: "scraper", trustLevel: "untrusted" },
      audience: "user",
    });

    const results = await provider.search("data", workspaceId, {
      provenance: { trustLevels: ["trusted"] },
      audience: ["user"],
      asOf,
      hybrid: { maxCandidates: 10 },
    });

    expect(results).toHaveLength(1);
    expect(results[0].entry.scope).toBe("doc1");
  });

  it("should deterministically rank tied scores", async () => {
    await provider.commit({
      workspaceId,
      scope: "zzz",
      content: "equal content",
    });

    await provider.commit({
      workspaceId,
      scope: "aaa",
      content: "equal content",
    });

    const results = await provider.search("equal", workspaceId);

    expect(results).toHaveLength(2);
    // Should be ordered by id when scores tie
    expect(results[0].entry.scope).toBe("aaa");
    expect(results[1].entry.scope).toBe("zzz");
  });
});
