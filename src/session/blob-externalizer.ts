/**
 * Blob Externalizer
 * Handles externalization of oversized content to verified artifacts with payload bounds
 */

import { createHash } from "node:crypto";
import type { ArtifactRef } from "../contracts/generated/artifact-ref.js";

/**
 * Blob content that may be externalized
 */
export interface BlobContent {
  data: string | Buffer;
  contentType?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Externalized blob reference
 */
export interface ExternalizedBlob {
  inline: false;
  artifactRef: ArtifactRef;
  truncated?: string; // Preview/summary of original content
  originalBytes: number;
}

/**
 * Inline blob (small enough to keep)
 */
export interface InlineBlob {
  inline: true;
  data: string;
  contentType?: string;
  bytes: number;
}

/**
 * Blob reference (either inline or externalized)
 */
export type BlobReference = InlineBlob | ExternalizedBlob;

/**
 * Externalization result
 */
export interface ExternalizationResult {
  ok: boolean;
  blob?: BlobReference;
  reason?: string;
}

/**
 * Payload bounds configuration
 */
export interface PayloadBounds {
  maxInlineBytes: number;
  maxTruncatedPreviewBytes: number;
  maxTotalPayloadBytes: number;
}

/**
 * Artifact storage interface
 */
export interface ArtifactStore {
  save(content: Buffer, kind: string, metadata: Record<string, unknown>): Promise<ArtifactRef>;
  retrieve(ref: ArtifactRef): Promise<Buffer | null>;
  verify(ref: ArtifactRef, content: Buffer): boolean;
}

/**
 * Default payload bounds
 */
export const DEFAULT_PAYLOAD_BOUNDS: PayloadBounds = {
  maxInlineBytes: 64 * 1024, // 64KB inline threshold
  maxTruncatedPreviewBytes: 1024, // 1KB preview
  maxTotalPayloadBytes: 10 * 1024 * 1024, // 10MB absolute limit
};

/**
 * Blob externalizer with verification
 */
export class BlobExternalizer {
  constructor(
    private readonly store: ArtifactStore,
    private readonly workspaceId: string,
    private readonly ownerRunId: string,
    private readonly bounds: PayloadBounds = DEFAULT_PAYLOAD_BOUNDS,
  ) {}

  /**
   * Process blob - inline or externalize based on size
   */
  async processBlob(content: BlobContent, kind: string = "blob"): Promise<ExternalizationResult> {
    const buffer = this.toBuffer(content.data);
    const bytes = buffer.byteLength;

    // Check absolute limit
    if (bytes > this.bounds.maxTotalPayloadBytes) {
      return {
        ok: false,
        reason: `Content exceeds maximum allowed size: ${bytes} > ${this.bounds.maxTotalPayloadBytes}`,
      };
    }

    // Small enough to inline
    if (bytes <= this.bounds.maxInlineBytes) {
      return {
        ok: true,
        blob: {
          inline: true,
          data: buffer.toString("utf8"),
          contentType: content.contentType,
          bytes,
        },
      };
    }

    // Externalize to artifact
    try {
      const artifactRef = await this.store.save(buffer, kind, {
        ...content.metadata,
        contentType: content.contentType,
        workspaceId: this.workspaceId,
        ownerRunId: this.ownerRunId,
      });

      // Verify artifact was saved correctly
      const verified = await this.verifyArtifact(artifactRef, buffer);
      if (!verified) {
        return {
          ok: false,
          reason: "Artifact verification failed after save",
        };
      }

      const truncated = this.createPreview(buffer, content.contentType);

      return {
        ok: true,
        blob: {
          inline: false,
          artifactRef,
          truncated,
          originalBytes: bytes,
        },
      };
    } catch (error) {
      return {
        ok: false,
        reason: `Failed to externalize blob: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
  }

  /**
   * Retrieve externalized blob
   */
  async retrieveBlob(ref: ExternalizedBlob): Promise<Buffer | null> {
    return this.store.retrieve(ref.artifactRef);
  }

  /**
   * Verify artifact integrity
   */
  async verifyArtifact(ref: ArtifactRef, expectedContent: Buffer): Promise<boolean> {
    if (ref.status !== "ready") {
      return false;
    }

    // Verify size
    if (ref.bytes !== expectedContent.byteLength) {
      return false;
    }

    // Verify SHA-256 hash
    const actualHash = this.computeSha256(expectedContent);
    if (actualHash !== ref.sha256) {
      return false;
    }

    return true;
  }

  /**
   * Check if content needs externalization
   */
  needsExternalization(content: string | Buffer): boolean {
    const bytes = Buffer.isBuffer(content) ? content.byteLength : Buffer.byteLength(content);
    return bytes > this.bounds.maxInlineBytes;
  }

  /**
   * Get content size in bytes
   */
  getContentSize(content: string | Buffer): number {
    return Buffer.isBuffer(content) ? content.byteLength : Buffer.byteLength(content);
  }

  /**
   * Create truncated preview
   */
  private createPreview(buffer: Buffer, contentType?: string): string {
    const maxBytes = this.bounds.maxTruncatedPreviewBytes;

    if (buffer.byteLength <= maxBytes) {
      return buffer.toString("utf8");
    }

    // Handle text content
    if (contentType?.startsWith("text/") || contentType === "application/json") {
      const text = buffer.toString("utf8", 0, maxBytes);
      const lastNewline = text.lastIndexOf("\n");
      if (lastNewline > 0) {
        return `${text.substring(0, lastNewline)}\n[... truncated ...]`;
      }
      return `${text}[... truncated ...]`;
    }

    // Handle binary content
    return `[Binary content, ${buffer.byteLength} bytes]`;
  }

  /**
   * Convert to buffer
   */
  private toBuffer(data: string | Buffer): Buffer {
    return Buffer.isBuffer(data) ? data : Buffer.from(data, "utf8");
  }

  /**
   * Compute SHA-256 hash
   */
  private computeSha256(buffer: Buffer): string {
    return createHash("sha256").update(buffer).digest("hex");
  }
}

/**
 * In-memory artifact store (for testing)
 */
export class InMemoryArtifactStore implements ArtifactStore {
  private artifacts: Map<string, { content: Buffer; ref: ArtifactRef }> = new Map();
  private idCounter = 1;

  async save(
    content: Buffer,
    kind: string,
    metadata: Record<string, unknown>,
  ): Promise<ArtifactRef> {
    const id = `artifact-${this.idCounter++}`;
    const sha256 = createHash("sha256").update(content).digest("hex");

    const ref: ArtifactRef = {
      id,
      workspaceId: (metadata.workspaceId as string) || "default-workspace",
      ownerRunId: (metadata.ownerRunId as string) || "default-run",
      kind,
      version: "v1",
      status: "ready",
      sha256,
      bytes: content.byteLength,
    };

    this.artifacts.set(id, { content, ref });

    return ref;
  }

  async retrieve(ref: ArtifactRef): Promise<Buffer | null> {
    const artifact = this.artifacts.get(ref.id);
    return artifact ? artifact.content : null;
  }

  verify(ref: ArtifactRef, content: Buffer): boolean {
    if (ref.status !== "ready") {
      return false;
    }

    const actualHash = createHash("sha256").update(content).digest("hex");
    return actualHash === ref.sha256 && content.byteLength === ref.bytes;
  }

  clear(): void {
    this.artifacts.clear();
    this.idCounter = 1;
  }

  size(): number {
    return this.artifacts.size;
  }
}
