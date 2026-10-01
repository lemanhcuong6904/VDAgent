import { beforeEach, describe, expect, it } from "vitest";
import {
  type BlobContent,
  BlobExternalizer,
  DEFAULT_PAYLOAD_BOUNDS,
  type ExternalizedBlob,
  type InlineBlob,
  InMemoryArtifactStore,
} from "../../src/session/blob-externalizer.js";

describe("BlobExternalizer", () => {
  let store: InMemoryArtifactStore;
  let externalizer: BlobExternalizer;

  beforeEach(() => {
    store = new InMemoryArtifactStore();
    externalizer = new BlobExternalizer(store, "workspace-1", "run-1");
  });

  describe("Initialization", () => {
    it("should initialize with default bounds", () => {
      expect(externalizer).toBeDefined();
    });

    it("should initialize with custom bounds", () => {
      const customBounds = {
        maxInlineBytes: 1024,
        maxTruncatedPreviewBytes: 512,
        maxTotalPayloadBytes: 1024 * 1024,
      };

      const customExternalizer = new BlobExternalizer(store, "workspace-1", "run-1", customBounds);

      expect(customExternalizer).toBeDefined();
    });
  });

  describe("Inline Content", () => {
    it("should keep small content inline", async () => {
      const content: BlobContent = {
        data: "Small content",
        contentType: "text/plain",
      };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob).toBeDefined();
      expect(result.blob!.inline).toBe(true);

      const inline = result.blob as InlineBlob;
      expect(inline.data).toBe("Small content");
      expect(inline.contentType).toBe("text/plain");
      expect(inline.bytes).toBe(13);
    });

    it("should inline content at exactly maxInlineBytes", async () => {
      const data = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes);
      const content: BlobContent = { data };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob!.inline).toBe(true);
    });

    it("should handle Buffer input", async () => {
      const buffer = Buffer.from("Buffer content", "utf8");
      const content: BlobContent = { data: buffer };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob!.inline).toBe(true);
      expect((result.blob as InlineBlob).data).toBe("Buffer content");
    });
  });

  describe("Externalized Content", () => {
    it("should externalize large content", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = {
        data: largeData,
        contentType: "text/plain",
      };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob).toBeDefined();
      expect(result.blob!.inline).toBe(false);

      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.artifactRef).toBeDefined();
      expect(externalized.artifactRef.status).toBe("ready");
      if (externalized.artifactRef.status !== "ready") throw new Error("Expected ready artifact");
      expect(externalized.artifactRef.sha256).toBeDefined();
      expect(externalized.originalBytes).toBe(largeData.length);
    });

    it("should create truncated preview for large content", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1000);
      const content: BlobContent = {
        data: largeData,
        contentType: "text/plain",
      };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.truncated).toBeDefined();
      expect(externalized.truncated!.length).toBeLessThan(largeData.length);
    });

    it("should handle binary content externalization", async () => {
      const binaryData = Buffer.alloc(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      for (let i = 0; i < binaryData.length; i++) {
        binaryData[i] = i % 256;
      }

      const content: BlobContent = {
        data: binaryData,
        contentType: "application/octet-stream",
      };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob!.inline).toBe(false);

      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.truncated).toContain("[Binary content");
    });

    it("should include metadata in artifact", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = {
        data: largeData,
        contentType: "text/plain",
        metadata: {
          source: "test",
          timestamp: "2024-01-01",
        },
      };

      const result = await externalizer.processBlob(content, "test-blob");

      expect(result.ok).toBe(true);
      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.artifactRef.kind).toBe("test-blob");
    });
  });

  describe("Payload Bounds Enforcement", () => {
    it("should reject content exceeding maxTotalPayloadBytes", async () => {
      const tooLarge = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxTotalPayloadBytes + 1);
      const content: BlobContent = { data: tooLarge };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(false);
      expect(result.reason).toContain("exceeds maximum allowed size");
    });

    it("should accept content at maxTotalPayloadBytes", async () => {
      const maxSize = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxTotalPayloadBytes);
      const content: BlobContent = { data: maxSize };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
    });

    it("should respect custom bounds", async () => {
      const customBounds = {
        maxInlineBytes: 100,
        maxTruncatedPreviewBytes: 50,
        maxTotalPayloadBytes: 1000,
      };

      const customExternalizer = new BlobExternalizer(store, "workspace-1", "run-1", customBounds);

      const data = "x".repeat(101);
      const content: BlobContent = { data };

      const result = await customExternalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob!.inline).toBe(false);
    });
  });

  describe("Artifact Verification", () => {
    it("should verify artifact after save", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = { data: largeData };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);

      const externalized = result.blob as ExternalizedBlob;
      const buffer = Buffer.from(largeData, "utf8");

      const verified = await externalizer.verifyArtifact(externalized.artifactRef, buffer);

      expect(verified).toBe(true);
    });

    it("should fail verification with wrong content", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = { data: largeData };

      const result = await externalizer.processBlob(content);
      expect(result.ok).toBe(true);

      const externalized = result.blob as ExternalizedBlob;
      const wrongBuffer = Buffer.from("wrong content", "utf8");

      const verified = await externalizer.verifyArtifact(externalized.artifactRef, wrongBuffer);

      expect(verified).toBe(false);
    });

    it("should fail verification with wrong size", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = { data: largeData };

      const result = await externalizer.processBlob(content);
      expect(result.ok).toBe(true);

      const externalized = result.blob as ExternalizedBlob;
      const wrongBuffer = Buffer.from(`${largeData}extra`, "utf8");

      const verified = await externalizer.verifyArtifact(externalized.artifactRef, wrongBuffer);

      expect(verified).toBe(false);
    });

    it("should fail verification for pending artifact", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = { data: largeData };

      const result = await externalizer.processBlob(content);
      expect(result.ok).toBe(true);

      const externalized = result.blob as ExternalizedBlob;
      const pendingRef = {
        ...externalized.artifactRef,
        status: "pending" as const,
      };

      const buffer = Buffer.from(largeData, "utf8");
      const verified = await externalizer.verifyArtifact(pendingRef, buffer);

      expect(verified).toBe(false);
    });
  });

  describe("Blob Retrieval", () => {
    it("should retrieve externalized blob", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = { data: largeData };

      const result = await externalizer.processBlob(content);
      expect(result.ok).toBe(true);

      const externalized = result.blob as ExternalizedBlob;
      const retrieved = await externalizer.retrieveBlob(externalized);

      expect(retrieved).not.toBeNull();
      expect(retrieved!.toString("utf8")).toBe(largeData);
    });

    it("should return null for missing artifact", async () => {
      const fakeRef: ExternalizedBlob = {
        inline: false,
        artifactRef: {
          id: "nonexistent",
          workspaceId: "workspace-1",
          ownerRunId: "run-1",
          kind: "blob",
          version: "v1",
          status: "ready",
          sha256: "0".repeat(64),
          bytes: 100,
        },
        originalBytes: 100,
      };

      const retrieved = await externalizer.retrieveBlob(fakeRef);
      expect(retrieved).toBeNull();
    });
  });

  describe("Preview Generation", () => {
    it("should create preview with truncation marker for text", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = {
        data: largeData,
        contentType: "text/plain",
      };

      const result = await externalizer.processBlob(content);

      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.truncated).toContain("[... truncated ...]");
    });

    it("should create binary preview for binary content", async () => {
      const binaryData = Buffer.alloc(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = {
        data: binaryData,
        contentType: "application/octet-stream",
      };

      const result = await externalizer.processBlob(content);

      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.truncated).toMatch(/\[Binary content, \d+ bytes\]/);
    });

    it("should handle JSON content type", async () => {
      const jsonData = JSON.stringify({ large: "x".repeat(100000) });
      const content: BlobContent = {
        data: jsonData,
        contentType: "application/json",
      };

      const result = await externalizer.processBlob(content);

      const externalized = result.blob as ExternalizedBlob;
      expect(externalized.truncated).toBeDefined();
    });

    it("should break at newline for better preview", async () => {
      const lines = Array.from({ length: 100 }, (_, i) => `Line ${i}`).join("\n");
      const content: BlobContent = {
        data: lines,
        contentType: "text/plain",
      };

      const result = await externalizer.processBlob(content);

      const externalized = result.blob as ExternalizedBlob;
      if (externalized.truncated) {
        expect(externalized.truncated).toContain("\n");
      }
    });
  });

  describe("Size Utilities", () => {
    it("should detect when externalization is needed", () => {
      const small = "small";
      const large = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);

      expect(externalizer.needsExternalization(small)).toBe(false);
      expect(externalizer.needsExternalization(large)).toBe(true);
    });

    it("should correctly compute content size for strings", () => {
      const text = "Hello, world!";
      const size = externalizer.getContentSize(text);

      expect(size).toBe(Buffer.byteLength(text));
    });

    it("should correctly compute content size for buffers", () => {
      const buffer = Buffer.from("Test buffer", "utf8");
      const size = externalizer.getContentSize(buffer);

      expect(size).toBe(buffer.byteLength);
    });

    it("should handle UTF-8 multibyte characters", () => {
      const text = "Hello 世界 🌍";
      const size = externalizer.getContentSize(text);

      expect(size).toBeGreaterThan(text.length); // Multibyte chars
    });
  });

  describe("InMemoryArtifactStore", () => {
    it("should save and retrieve artifact", async () => {
      const content = Buffer.from("test content", "utf8");
      const ref = await store.save(content, "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      expect(ref.id).toBeDefined();
      expect(ref.status).toBe("ready");
      if (ref.status !== "ready") throw new Error("Expected ready artifact");
      expect(ref.sha256).toBeDefined();
      expect(ref.bytes).toBe(content.byteLength);

      const retrieved = await store.retrieve(ref);
      expect(retrieved).toEqual(content);
    });

    it("should verify artifact with matching content", async () => {
      const content = Buffer.from("verify test", "utf8");
      const ref = await store.save(content, "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      const verified = store.verify(ref, content);
      expect(verified).toBe(true);
    });

    it("should fail verification with wrong content", async () => {
      const content = Buffer.from("original", "utf8");
      const ref = await store.save(content, "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      const wrong = Buffer.from("modified", "utf8");
      const verified = store.verify(ref, wrong);
      expect(verified).toBe(false);
    });

    it("should return null for nonexistent artifact", async () => {
      const fakeRef = {
        id: "nonexistent",
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
        kind: "test",
        version: "v1",
        status: "ready" as const,
        sha256: "0".repeat(64),
        bytes: 100,
      };

      const retrieved = await store.retrieve(fakeRef);
      expect(retrieved).toBeNull();
    });

    it("should track store size", async () => {
      expect(store.size()).toBe(0);

      await store.save(Buffer.from("test1", "utf8"), "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      expect(store.size()).toBe(1);

      await store.save(Buffer.from("test2", "utf8"), "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      expect(store.size()).toBe(2);
    });

    it("should clear all artifacts", async () => {
      await store.save(Buffer.from("test1", "utf8"), "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });
      await store.save(Buffer.from("test2", "utf8"), "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      expect(store.size()).toBe(2);

      store.clear();

      expect(store.size()).toBe(0);
    });

    it("should generate unique artifact IDs", async () => {
      const ref1 = await store.save(Buffer.from("test1", "utf8"), "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      const ref2 = await store.save(Buffer.from("test2", "utf8"), "test", {
        workspaceId: "workspace-1",
        ownerRunId: "run-1",
      });

      expect(ref1.id).not.toBe(ref2.id);
    });
  });

  describe("Edge Cases", () => {
    it("should handle empty content", async () => {
      const content: BlobContent = { data: "" };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
      expect(result.blob!.inline).toBe(true);
      expect((result.blob as InlineBlob).bytes).toBe(0);
    });

    it("should handle content at boundary exactly", async () => {
      const boundary = DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes;
      const atBoundary = "x".repeat(boundary);
      const overBoundary = "x".repeat(boundary + 1);

      const result1 = await externalizer.processBlob({ data: atBoundary });
      expect(result1.blob!.inline).toBe(true);

      const result2 = await externalizer.processBlob({ data: overBoundary });
      expect(result2.blob!.inline).toBe(false);
    });

    it("should handle content without content type", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = { data: largeData };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
    });

    it("should handle content without metadata", async () => {
      const largeData = "x".repeat(DEFAULT_PAYLOAD_BOUNDS.maxInlineBytes + 1);
      const content: BlobContent = {
        data: largeData,
        contentType: "text/plain",
      };

      const result = await externalizer.processBlob(content);

      expect(result.ok).toBe(true);
    });
  });
});
