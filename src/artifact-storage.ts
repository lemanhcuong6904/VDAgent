/**
 * Artifact Storage - M11.1
 * Metadata-first publication with SHA-256/length readback, owner/isolation/version tracking
 */

import { createHash } from "node:crypto";
import type { Pool } from "pg";

export interface ArtifactMetadata {
  id: string;
  workspaceId: string;
  ownerUserId?: string | null;
  ownerRunId: string;
  kind: string;
  version: string;
  status: "pending" | "ready" | "failed";
  sha256: string | null;
  bytes: number | null;
  metadata: Record<string, unknown>;
  createdAt: Date;
  readyAt: Date | null;
}

export interface StoreArtifactParams {
  workspaceId: string;
  ownerUserId?: string;
  ownerRunId: string;
  kind: string;
  version: string;
  content: Buffer;
  metadata?: Record<string, unknown>;
}

export interface StoreArtifactResult {
  id: string;
  sha256: string;
  bytes: number;
}

export class ArtifactStorage {
  constructor(private readonly database: Pool) {}

  /**
   * Store artifact with metadata-first approach
   * 1. Compute SHA-256 hash and size
   * 2. Insert metadata record (status: pending)
   * 3. Store content in separate table
   * 4. Update status to ready
   * 5. Return hash and size for verification
   */
  async store(params: StoreArtifactParams): Promise<StoreArtifactResult> {
    const id = this.generateArtifactId(params.kind);
    const sha256 = this.computeSha256(params.content);
    const bytes = params.content.length;

    // Step 1: Insert metadata (status: pending)
    await this.database.query(
      `INSERT INTO artifacts (id, workspace_id, owner_user_id, owner_run_id, kind, version, status, sha256, bytes, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)`,
      [
        id,
        params.workspaceId,
        params.ownerUserId ?? null,
        params.ownerRunId,
        params.kind,
        params.version,
        "pending",
        sha256,
        bytes,
        JSON.stringify(params.metadata || {}),
      ],
    );

    try {
      // Step 2: Store content
      await this.database.query(
        `INSERT INTO artifact_contents (artifact_id, content)
         VALUES ($1, $2)`,
        [id, params.content],
      );

      // Step 3: Mark as ready
      await this.database.query(
        `UPDATE artifacts SET status = $1, ready_at = now()
         WHERE id = $2`,
        ["ready", id],
      );

      return { id, sha256, bytes };
    } catch (error) {
      // Rollback: mark as failed
      await this.database.query(`UPDATE artifacts SET status = $1 WHERE id = $2`, ["failed", id]);
      throw error;
    }
  }

  /**
   * Verify artifact integrity by SHA-256 hash
   */
  async verify(params: { id: string; sha256: string }): Promise<boolean> {
    const result = await this.database.query<{ sha256: string | null; status: string }>(
      `SELECT sha256, status FROM artifacts WHERE id = $1`,
      [params.id],
    );

    if (result.rows.length === 0) return false;

    const artifact = result.rows[0];
    return artifact.status === "ready" && artifact.sha256 === params.sha256;
  }

  /**
   * Mark artifact as ready (for streaming uploads)
   */
  async markReady(id: string): Promise<void> {
    await this.database.query(
      `UPDATE artifacts SET status = $1, ready_at = now()
       WHERE id = $2 AND status = $3`,
      ["ready", id, "pending"],
    );
  }

  /**
   * Get artifact metadata by ID
   */
  async getMetadata(
    id: string,
    workspaceId: string,
    ownerUserId?: string,
  ): Promise<ArtifactMetadata | null> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      owner_user_id: string | null;
      owner_run_id: string;
      kind: string;
      version: string;
      status: "pending" | "ready" | "failed";
      sha256: string | null;
      bytes: string | null;
      metadata: Record<string, unknown>;
      created_at: Date;
      ready_at: Date | null;
    }>(
      `SELECT id, workspace_id, owner_user_id, owner_run_id, kind, version, status, sha256, bytes, metadata, created_at, ready_at
       FROM artifacts
       WHERE id = $1 AND workspace_id = $2 AND ($3::text IS NULL OR owner_user_id = $3)`,
      [id, workspaceId, ownerUserId ?? null],
    );

    if (result.rows.length === 0) return null;

    const row = result.rows[0];
    return {
      id: row.id,
      workspaceId: row.workspace_id,
      ownerUserId: row.owner_user_id,
      ownerRunId: row.owner_run_id,
      kind: row.kind,
      version: row.version,
      status: row.status,
      sha256: row.sha256,
      bytes: row.bytes === null ? null : Number(row.bytes),
      metadata: row.metadata,
      createdAt: row.created_at,
      readyAt: row.ready_at,
    };
  }

  /**
   * Get artifact content
   */
  async getContent(id: string, workspaceId: string, ownerUserId?: string): Promise<Buffer | null> {
    // Verify workspace ownership
    const metadata = await this.getMetadata(id, workspaceId, ownerUserId);
    if (metadata?.status !== "ready") return null;

    const result = await this.database.query<{ content: Buffer }>(
      `SELECT content FROM artifact_contents WHERE artifact_id = $1`,
      [id],
    );

    return result.rows[0]?.content || null;
  }

  /**
   * List artifacts by workspace
   */
  async listByWorkspace(
    workspaceId: string,
    options: { limit?: number; offset?: number; ownerUserId?: string } = {},
  ): Promise<ArtifactMetadata[]> {
    const limit = options.limit || 100;
    const offset = options.offset || 0;

    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      owner_user_id: string | null;
      owner_run_id: string;
      kind: string;
      version: string;
      status: "pending" | "ready" | "failed";
      sha256: string | null;
      bytes: string | null;
      metadata: Record<string, unknown>;
      created_at: Date;
      ready_at: Date | null;
    }>(
      `SELECT id, workspace_id, owner_user_id, owner_run_id, kind, version, status, sha256, bytes, metadata, created_at, ready_at
       FROM artifacts
       WHERE workspace_id = $1 AND ($4::text IS NULL OR owner_user_id = $4)
       ORDER BY created_at DESC
       LIMIT $2 OFFSET $3`,
      [workspaceId, limit, offset, options.ownerUserId ?? null],
    );

    return result.rows.map((row) => ({
      id: row.id,
      workspaceId: row.workspace_id,
      ownerUserId: row.owner_user_id,
      ownerRunId: row.owner_run_id,
      kind: row.kind,
      version: row.version,
      status: row.status,
      sha256: row.sha256,
      bytes: row.bytes === null ? null : Number(row.bytes),
      metadata: row.metadata,
      createdAt: row.created_at,
      readyAt: row.ready_at,
    }));
  }

  /**
   * List artifacts by owner run
   */
  async listByOwnerRun(ownerRunId: string, ownerUserId?: string): Promise<ArtifactMetadata[]> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      owner_user_id: string | null;
      owner_run_id: string;
      kind: string;
      version: string;
      status: "pending" | "ready" | "failed";
      sha256: string | null;
      bytes: string | null;
      metadata: Record<string, unknown>;
      created_at: Date;
      ready_at: Date | null;
    }>(
      `SELECT id, workspace_id, owner_user_id, owner_run_id, kind, version, status, sha256, bytes, metadata, created_at, ready_at
       FROM artifacts
       WHERE owner_run_id = $1 AND ($2::text IS NULL OR owner_user_id = $2)
       ORDER BY created_at ASC`,
      [ownerRunId, ownerUserId ?? null],
    );

    return result.rows.map((row) => ({
      id: row.id,
      workspaceId: row.workspace_id,
      ownerUserId: row.owner_user_id,
      ownerRunId: row.owner_run_id,
      kind: row.kind,
      version: row.version,
      status: row.status,
      sha256: row.sha256,
      bytes: row.bytes === null ? null : Number(row.bytes),
      metadata: row.metadata,
      createdAt: row.created_at,
      readyAt: row.ready_at,
    }));
  }

  private generateArtifactId(kind: string): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 10);
    const prefix = kind.slice(0, 3).toLowerCase();
    return `${prefix}_${timestamp}${random}`;
  }

  private computeSha256(content: Buffer): string {
    return createHash("sha256").update(content).digest("hex");
  }
}
