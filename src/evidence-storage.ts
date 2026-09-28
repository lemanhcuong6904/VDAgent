/**
 * Evidence Storage - M11.2
 * Evidence refs link source/run/tool/model/artifact revision
 * Missing evidence = unavailable verification
 */

import { createHash } from "node:crypto";
import type { Pool, PoolClient } from "pg";

export type EvidenceKind = "source" | "tool_call" | "model_call" | "artifact_ref" | "checkpoint";
export type VerificationStatus = "unverified" | "verified" | "unavailable";

export interface BaseEvidence {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  kind: EvidenceKind;
  verification: VerificationStatus;
  metadata: Record<string, unknown>;
  createdAt: Date;
  verifiedAt: Date | null;
}

export interface SourceEvidence extends BaseEvidence {
  kind: "source";
  sourceType: string;
  sourceLocation: string;
  sourceRevision: string;
}

export interface ToolCallEvidence extends BaseEvidence {
  kind: "tool_call";
  toolId: string;
  toolInputHash: string;
  toolOutputHash: string;
}

export interface ModelCallEvidence extends BaseEvidence {
  kind: "model_call";
  modelId: string;
  modelInputHash: string;
  modelOutputHash: string;
  modelTokens: {
    input: number;
    output: number;
    cacheRead?: number;
    cacheWrite?: number;
  };
}

export interface ArtifactRefEvidence extends BaseEvidence {
  kind: "artifact_ref";
  artifactId: string;
  artifactSha256: string;
}

export interface CheckpointEvidence extends BaseEvidence {
  kind: "checkpoint";
  checkpointId: string;
  checkpointRevision: number;
}

export type Evidence =
  | SourceEvidence
  | ToolCallEvidence
  | ModelCallEvidence
  | ArtifactRefEvidence
  | CheckpointEvidence;

export interface RecordSourceParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  sourceType: string;
  sourceLocation: string;
  sourceRevision: string;
  metadata?: Record<string, unknown>;
}

export interface RecordToolCallParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  toolId: string;
  toolInput: unknown;
  toolOutput: unknown;
  metadata?: Record<string, unknown>;
}

export interface RecordModelCallParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  modelId: string;
  modelInput: string;
  modelOutput: string;
  tokens: {
    input: number;
    output: number;
    cacheRead?: number;
    cacheWrite?: number;
  };
  metadata?: Record<string, unknown>;
}

export interface RecordArtifactRefParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  artifactId: string;
  artifactSha256: string;
  metadata?: Record<string, unknown>;
}

export interface RecordCheckpointParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  checkpointId: string;
  checkpointRevision: number;
  metadata?: Record<string, unknown>;
}

export interface EvidenceStorageOptions {
  /** Verify artifact ownership, readiness and bytes before accepting an artifact ref. */
  requireArtifactVerification?: boolean;
}

export class EvidenceStorage {
  constructor(
    private readonly database: Pool,
    private readonly options: EvidenceStorageOptions = {},
  ) {}

  private async artifactMatches(
    artifactId: string,
    workspaceId: string,
    expectedSha256: string,
    queryable: Pick<PoolClient, "query"> = this.database,
  ): Promise<boolean> {
    const result = await queryable.query<{
      workspace_id: string;
      status: string;
      sha256: string | null;
      content: Buffer | null;
    }>(
      `SELECT a.workspace_id, a.status, a.sha256, c.content
       FROM artifacts a
       JOIN artifact_contents c ON c.artifact_id = a.id
       WHERE a.id = $1 AND a.workspace_id = $2
       FOR SHARE OF a, c`,
      [artifactId, workspaceId],
    );
    const artifact = result.rows[0];
    if (
      !artifact ||
      artifact.workspace_id !== workspaceId ||
      artifact.status !== "ready" ||
      !artifact.content
    )
      return false;
    const actualSha256 = createHash("sha256").update(artifact.content).digest("hex");
    return artifact.sha256 === expectedSha256 && actualSha256 === expectedSha256;
  }

  /**
   * Record source evidence (file, git commit, external resource)
   */
  async recordSource(params: RecordSourceParams): Promise<string> {
    const id = this.generateEvidenceId("src");

    await this.database.query(
      `INSERT INTO evidence_refs
       (id, workspace_id, run_id, attempt_id, kind, verification,
        source_type, source_location, source_revision, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)`,
      [
        id,
        params.workspaceId,
        params.runId,
        params.attemptId,
        "source",
        "unverified",
        params.sourceType,
        params.sourceLocation,
        params.sourceRevision,
        JSON.stringify(params.metadata || {}),
      ],
    );

    return id;
  }

  /**
   * Record tool call evidence with input/output hashes
   */
  async recordToolCall(params: RecordToolCallParams): Promise<string> {
    const id = this.generateEvidenceId("tool");
    const inputHash = this.hashJson(params.toolInput);
    const outputHash = this.hashJson(params.toolOutput);

    await this.database.query(
      `INSERT INTO evidence_refs
       (id, workspace_id, run_id, attempt_id, kind, verification,
        tool_id, tool_input_hash, tool_output_hash, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)`,
      [
        id,
        params.workspaceId,
        params.runId,
        params.attemptId,
        "tool_call",
        "unverified",
        params.toolId,
        inputHash,
        outputHash,
        JSON.stringify(params.metadata || {}),
      ],
    );

    return id;
  }

  /**
   * Record model call evidence with input/output hashes and token counts
   */
  async recordModelCall(params: RecordModelCallParams): Promise<string> {
    const id = this.generateEvidenceId("model");
    const inputHash = this.hashString(params.modelInput);
    const outputHash = this.hashString(params.modelOutput);

    await this.database.query(
      `INSERT INTO evidence_refs
       (id, workspace_id, run_id, attempt_id, kind, verification,
        model_id, model_input_hash, model_output_hash, model_tokens, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb)`,
      [
        id,
        params.workspaceId,
        params.runId,
        params.attemptId,
        "model_call",
        "unverified",
        params.modelId,
        inputHash,
        outputHash,
        JSON.stringify(params.tokens),
        JSON.stringify(params.metadata || {}),
      ],
    );

    return id;
  }

  /**
   * Record artifact reference evidence
   */
  async recordArtifactRef(params: RecordArtifactRefParams): Promise<string> {
    const artifactSha256 = params.artifactSha256.toLowerCase();
    if (!/^[a-f0-9]{64}$/.test(artifactSha256)) {
      throw new Error("artifact_sha256 must be a lowercase SHA-256 digest");
    }
    const id = this.generateEvidenceId("art");
    const client = await this.database.connect();
    try {
      await client.query("BEGIN");
      if (
        this.options.requireArtifactVerification &&
        !(await this.artifactMatches(params.artifactId, params.workspaceId, artifactSha256, client))
      ) {
        throw new Error("artifact_ref_not_verifiable");
      }
      await client.query(
        `INSERT INTO evidence_refs
         (id, workspace_id, run_id, attempt_id, kind, verification,
          artifact_id, artifact_sha256, metadata)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)`,
        [
          id,
          params.workspaceId,
          params.runId,
          params.attemptId,
          "artifact_ref",
          "unverified",
          params.artifactId,
          artifactSha256,
          JSON.stringify(params.metadata || {}),
        ],
      );
      await client.query("COMMIT");
      return id;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  /**
   * Record checkpoint evidence
   */
  async recordCheckpoint(params: RecordCheckpointParams): Promise<string> {
    const id = this.generateEvidenceId("ckpt");

    await this.database.query(
      `INSERT INTO evidence_refs
       (id, workspace_id, run_id, attempt_id, kind, verification,
        checkpoint_id, checkpoint_revision, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)`,
      [
        id,
        params.workspaceId,
        params.runId,
        params.attemptId,
        "checkpoint",
        "unverified",
        params.checkpointId,
        params.checkpointRevision,
        JSON.stringify(params.metadata || {}),
      ],
    );

    return id;
  }

  /**
   * Mark evidence as verified
   */
  async markVerified(evidenceId: string, workspaceId: string): Promise<boolean> {
    const client = await this.database.connect();
    try {
      await client.query("BEGIN");
      const row = await client.query<{
        workspace_id: string;
        kind: EvidenceKind;
        verification: VerificationStatus;
        artifact_id: string | null;
        artifact_sha256: string | null;
      }>(
        `SELECT workspace_id, kind, verification, artifact_id, artifact_sha256
         FROM evidence_refs WHERE id = $1 AND workspace_id = $2
         FOR UPDATE`,
        [evidenceId, workspaceId],
      );
      const evidence = row.rows[0];
      if (evidence?.verification !== "unverified") {
        await client.query("COMMIT");
        return false;
      }
      if (
        evidence.kind === "artifact_ref" &&
        (!evidence.artifact_id ||
          !evidence.artifact_sha256 ||
          !(await this.artifactMatches(
            evidence.artifact_id,
            evidence.workspace_id,
            evidence.artifact_sha256,
            client,
          )))
      ) {
        await client.query(
          `UPDATE evidence_refs SET verification = $1, verified_at = NULL
           WHERE id = $2 AND workspace_id = $3`,
          ["unavailable", evidenceId, workspaceId],
        );
        await client.query("COMMIT");
        return false;
      }
      const updated = await client.query(
        `UPDATE evidence_refs
         SET verification = $1, verified_at = now()
         WHERE id = $2 AND verification = $3 AND workspace_id = $4`,
        ["verified", evidenceId, "unverified", workspaceId],
      );
      await client.query("COMMIT");
      return updated.rowCount === 1;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  /**
   * Mark evidence as unavailable (e.g., artifact deleted, source not found)
   */
  async markUnavailable(evidenceId: string, workspaceId: string): Promise<boolean> {
    const updated = await this.database.query(
      `UPDATE evidence_refs
       SET verification = $1, verified_at = NULL
       WHERE id = $2 AND workspace_id = $3`,
      ["unavailable", evidenceId, workspaceId],
    );
    return updated.rowCount === 1;
  }

  /**
   * Get evidence by ID
   */
  async get(
    evidenceId: string,
    workspaceId: string,
    ownerUserId?: string,
  ): Promise<Evidence | null> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      kind: EvidenceKind;
      verification: VerificationStatus;
      source_type: string | null;
      source_location: string | null;
      source_revision: string | null;
      tool_id: string | null;
      tool_input_hash: string | null;
      tool_output_hash: string | null;
      model_id: string | null;
      model_input_hash: string | null;
      model_output_hash: string | null;
      model_tokens: { input: number; output: number } | null;
      artifact_id: string | null;
      artifact_sha256: string | null;
      checkpoint_id: string | null;
      checkpoint_revision: number | null;
      metadata: Record<string, unknown>;
      created_at: Date;
      verified_at: Date | null;
    }>(
      `SELECT e.* FROM evidence_refs e
       WHERE e.id = $1 AND e.workspace_id = $2
         AND ($3::text IS NULL OR
           EXISTS (
             SELECT 1 FROM platform_runs r
             WHERE r.id = e.run_id AND r.space_id = e.workspace_id AND r.user_id = $3
           ) OR EXISTS (
             SELECT 1 FROM web_invocations i
             JOIN web_tasks t ON t.id = i.task_id
             LEFT JOIN platform_runs r ON r.id = i.platform_run_id
             WHERE i.id = e.run_id AND i.user_id = $3
               AND (r.id IS NULL OR r.space_id = e.workspace_id)
           ))`,
      [evidenceId, workspaceId, ownerUserId ?? null],
    );

    if (result.rows.length === 0) return null;

    return this.mapRowToEvidence(result.rows[0]);
  }

  /**
   * List evidence by run
   */
  async listByRun(runId: string, workspaceId: string): Promise<Evidence[]> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      kind: EvidenceKind;
      verification: VerificationStatus;
      source_type: string | null;
      source_location: string | null;
      source_revision: string | null;
      tool_id: string | null;
      tool_input_hash: string | null;
      tool_output_hash: string | null;
      model_id: string | null;
      model_input_hash: string | null;
      model_output_hash: string | null;
      model_tokens: { input: number; output: number } | null;
      artifact_id: string | null;
      artifact_sha256: string | null;
      checkpoint_id: string | null;
      checkpoint_revision: number | null;
      metadata: Record<string, unknown>;
      created_at: Date;
      verified_at: Date | null;
    }>(
      `SELECT * FROM evidence_refs
       WHERE run_id = $1 AND workspace_id = $2
       ORDER BY created_at ASC`,
      [runId, workspaceId],
    );

    return result.rows.map((row) => this.mapRowToEvidence(row));
  }

  /**
   * List evidence by artifact
   */
  async listByArtifact(artifactId: string, workspaceId: string): Promise<ArtifactRefEvidence[]> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      kind: "artifact_ref";
      verification: VerificationStatus;
      artifact_id: string;
      artifact_sha256: string;
      metadata: Record<string, unknown>;
      created_at: Date;
      verified_at: Date | null;
    }>(
      `SELECT * FROM evidence_refs
       WHERE artifact_id = $1 AND workspace_id = $2 AND kind = $3
       ORDER BY created_at ASC`,
      [artifactId, workspaceId, "artifact_ref"],
    );

    return result.rows.map((row) => ({
      id: row.id,
      workspaceId: row.workspace_id,
      runId: row.run_id,
      attemptId: row.attempt_id,
      kind: row.kind,
      verification: row.verification,
      artifactId: row.artifact_id,
      artifactSha256: row.artifact_sha256,
      metadata: row.metadata,
      createdAt: row.created_at,
      verifiedAt: row.verified_at,
    }));
  }

  /**
   * Count evidence by verification status
   */
  async countByStatus(
    runId: string,
    workspaceId: string,
  ): Promise<Record<VerificationStatus, number>> {
    const result = await this.database.query<{ verification: VerificationStatus; count: string }>(
      `SELECT verification, COUNT(*) as count
       FROM evidence_refs
       WHERE run_id = $1 AND workspace_id = $2
       GROUP BY verification`,
      [runId, workspaceId],
    );

    const counts: Record<VerificationStatus, number> = {
      unverified: 0,
      verified: 0,
      unavailable: 0,
    };

    for (const row of result.rows) {
      counts[row.verification] = parseInt(row.count, 10);
    }

    return counts;
  }

  private generateEvidenceId(prefix: string): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 10);
    return `${prefix}_${timestamp}${random}`;
  }

  private hashString(content: string): string {
    return createHash("sha256").update(content, "utf-8").digest("hex");
  }

  private hashJson(content: unknown): string {
    return this.hashString(canonicalJson(content));
  }

  private mapRowToEvidence(row: {
    id: string;
    workspace_id: string;
    run_id: string;
    attempt_id: string;
    kind: EvidenceKind;
    verification: VerificationStatus;
    source_type: string | null;
    source_location: string | null;
    source_revision: string | null;
    tool_id: string | null;
    tool_input_hash: string | null;
    tool_output_hash: string | null;
    model_id: string | null;
    model_input_hash: string | null;
    model_output_hash: string | null;
    model_tokens: { input: number; output: number } | null;
    artifact_id: string | null;
    artifact_sha256: string | null;
    checkpoint_id: string | null;
    checkpoint_revision: number | null;
    metadata: Record<string, unknown>;
    created_at: Date;
    verified_at: Date | null;
  }): Evidence {
    const base = {
      id: row.id,
      workspaceId: row.workspace_id,
      runId: row.run_id,
      attemptId: row.attempt_id,
      verification: row.verification,
      metadata: row.metadata,
      createdAt: row.created_at,
      verifiedAt: row.verified_at,
    };

    switch (row.kind) {
      case "source":
        return {
          ...base,
          kind: "source",
          sourceType: requireEvidenceField(row.source_type, "source_type"),
          sourceLocation: requireEvidenceField(row.source_location, "source_location"),
          sourceRevision: requireEvidenceField(row.source_revision, "source_revision"),
        };
      case "tool_call":
        return {
          ...base,
          kind: "tool_call",
          toolId: requireEvidenceField(row.tool_id, "tool_id"),
          toolInputHash: requireEvidenceField(row.tool_input_hash, "tool_input_hash"),
          toolOutputHash: requireEvidenceField(row.tool_output_hash, "tool_output_hash"),
        };
      case "model_call":
        return {
          ...base,
          kind: "model_call",
          modelId: requireEvidenceField(row.model_id, "model_id"),
          modelInputHash: requireEvidenceField(row.model_input_hash, "model_input_hash"),
          modelOutputHash: requireEvidenceField(row.model_output_hash, "model_output_hash"),
          modelTokens: requireEvidenceField(row.model_tokens, "model_tokens"),
        };
      case "artifact_ref":
        return {
          ...base,
          kind: "artifact_ref",
          artifactId: requireEvidenceField(row.artifact_id, "artifact_id"),
          artifactSha256: requireEvidenceField(row.artifact_sha256, "artifact_sha256"),
        };
      case "checkpoint":
        return {
          ...base,
          kind: "checkpoint",
          checkpointId: requireEvidenceField(row.checkpoint_id, "checkpoint_id"),
          checkpointRevision: requireEvidenceField(row.checkpoint_revision, "checkpoint_revision"),
        };
    }
  }
}

function requireEvidenceField<T>(value: T | null, field: string): T {
  if (value === null) throw new Error(`Evidence row is missing required field: ${field}`);
  return value;
}

/** Canonical JSON keeps evidence hashes stable when object insertion order differs. */
function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "bigint") return JSON.stringify(`${value}n`);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(String(value));
}
