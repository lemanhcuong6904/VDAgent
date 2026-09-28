/**
 * Terminal Receipt Storage - M11.3
 * Immutable terminal receipt, identical replay no-op, changed replay conflict
 */

import { createHash } from "node:crypto";
import type { Pool } from "pg";

export type ReceiptStatus = "success" | "failure" | "timeout" | "cancelled";

export interface TerminalReceipt {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  status: ReceiptStatus;
  exitCode: number | null;
  inputHash: string;
  outputHash: string | null;
  artifactIds: string[];
  evidenceCount: number;
  verifiedEvidenceCount: number;
  durationMs: number | null;
  tokensInput: number | null;
  tokensOutput: number | null;
  sealedAt: Date;
  metadata: Record<string, unknown>;
}

export interface SealReceiptParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  status: ReceiptStatus;
  exitCode?: number;
  input: unknown;
  output?: unknown;
  artifactIds?: string[];
  evidenceCount?: number;
  verifiedEvidenceCount?: number;
  durationMs?: number;
  tokensInput?: number;
  tokensOutput?: number;
  metadata?: Record<string, unknown>;
}

export interface ReplayCheckResult {
  exists: boolean;
  identical: boolean;
  conflict: boolean;
  existingReceipt?: TerminalReceipt;
}

export class TerminalReceiptStorage {
  constructor(private readonly database: Pool) {}

  /**
   * Seal a terminal receipt (immutable once created)
   */
  async seal(params: SealReceiptParams): Promise<TerminalReceipt> {
    const id = this.generateReceiptId();
    const inputHash = this.hashJson(params.input);
    const outputHash = params.output ? this.hashJson(params.output) : null;

    await this.database.query(
      `INSERT INTO terminal_receipts
       (id, workspace_id, run_id, attempt_id, status, exit_code,
        input_hash, output_hash, artifact_ids, evidence_count, verified_evidence_count,
        duration_ms, tokens_input, tokens_output, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, $14, $15::jsonb)`,
      [
        id,
        params.workspaceId,
        params.runId,
        params.attemptId,
        params.status,
        params.exitCode ?? null,
        inputHash,
        outputHash,
        JSON.stringify(params.artifactIds || []),
        params.evidenceCount ?? 0,
        params.verifiedEvidenceCount ?? 0,
        params.durationMs ?? null,
        params.tokensInput ?? null,
        params.tokensOutput ?? null,
        JSON.stringify(params.metadata || {}),
      ],
    );

    return {
      id,
      workspaceId: params.workspaceId,
      runId: params.runId,
      attemptId: params.attemptId,
      status: params.status,
      exitCode: params.exitCode ?? null,
      inputHash,
      outputHash,
      artifactIds: params.artifactIds || [],
      evidenceCount: params.evidenceCount ?? 0,
      verifiedEvidenceCount: params.verifiedEvidenceCount ?? 0,
      durationMs: params.durationMs ?? null,
      tokensInput: params.tokensInput ?? null,
      tokensOutput: params.tokensOutput ?? null,
      sealedAt: new Date(),
      metadata: params.metadata || {},
    };
  }

  /**
   * Check for replay: identical input = no-op, different output = conflict
   */
  async checkReplay(workspaceId: string, input: unknown): Promise<ReplayCheckResult> {
    const inputHash = this.hashJson(input);

    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      status: ReceiptStatus;
      exit_code: number | null;
      input_hash: string;
      output_hash: string | null;
      artifact_ids: string[];
      evidence_count: number;
      verified_evidence_count: number;
      duration_ms: string | null;
      tokens_input: number | null;
      tokens_output: number | null;
      sealed_at: Date;
      metadata: Record<string, unknown>;
    }>(
      `SELECT * FROM terminal_receipts
       WHERE workspace_id = $1 AND input_hash = $2
       ORDER BY sealed_at DESC
       LIMIT 1`,
      [workspaceId, inputHash],
    );

    if (result.rows.length === 0) {
      return { exists: false, identical: false, conflict: false };
    }

    const existing = this.mapRowToReceipt(result.rows[0]);

    return {
      exists: true,
      identical: true,
      conflict: false,
      existingReceipt: existing,
    };
  }

  /**
   * Check for conflict: same input but would produce different output
   */
  async checkConflict(
    workspaceId: string,
    input: unknown,
    output: unknown,
  ): Promise<ReplayCheckResult> {
    const inputHash = this.hashJson(input);
    const outputHash = this.hashJson(output);

    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      status: ReceiptStatus;
      exit_code: number | null;
      input_hash: string;
      output_hash: string | null;
      artifact_ids: string[];
      evidence_count: number;
      verified_evidence_count: number;
      duration_ms: string | null;
      tokens_input: number | null;
      tokens_output: number | null;
      sealed_at: Date;
      metadata: Record<string, unknown>;
    }>(
      `SELECT * FROM terminal_receipts
       WHERE workspace_id = $1 AND input_hash = $2
       ORDER BY sealed_at DESC
       LIMIT 1`,
      [workspaceId, inputHash],
    );

    if (result.rows.length === 0) {
      return { exists: false, identical: false, conflict: false };
    }

    const existing = this.mapRowToReceipt(result.rows[0]);
    const identical = existing.outputHash === outputHash;

    return {
      exists: true,
      identical,
      conflict: !identical,
      existingReceipt: existing,
    };
  }

  /**
   * Get receipt by ID
   */
  async get(receiptId: string, workspaceId: string): Promise<TerminalReceipt | null> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      status: ReceiptStatus;
      exit_code: number | null;
      input_hash: string;
      output_hash: string | null;
      artifact_ids: string[];
      evidence_count: number;
      verified_evidence_count: number;
      duration_ms: string | null;
      tokens_input: number | null;
      tokens_output: number | null;
      sealed_at: Date;
      metadata: Record<string, unknown>;
    }>(`SELECT * FROM terminal_receipts WHERE id = $1 AND workspace_id = $2`, [
      receiptId,
      workspaceId,
    ]);

    if (result.rows.length === 0) return null;

    return this.mapRowToReceipt(result.rows[0]);
  }

  /**
   * Get receipt by run ID
   */
  async getByRun(runId: string, workspaceId: string): Promise<TerminalReceipt | null> {
    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      status: ReceiptStatus;
      exit_code: number | null;
      input_hash: string;
      output_hash: string | null;
      artifact_ids: string[];
      evidence_count: number;
      verified_evidence_count: number;
      duration_ms: string | null;
      tokens_input: number | null;
      tokens_output: number | null;
      sealed_at: Date;
      metadata: Record<string, unknown>;
    }>(
      `SELECT * FROM terminal_receipts
       WHERE run_id = $1 AND workspace_id = $2
       ORDER BY sealed_at DESC
       LIMIT 1`,
      [runId, workspaceId],
    );

    if (result.rows.length === 0) return null;

    return this.mapRowToReceipt(result.rows[0]);
  }

  /**
   * List receipts by workspace
   */
  async listByWorkspace(
    workspaceId: string,
    options?: { limit?: number; offset?: number },
  ): Promise<TerminalReceipt[]> {
    const limit = options?.limit ?? 100;
    const offset = options?.offset ?? 0;

    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      status: ReceiptStatus;
      exit_code: number | null;
      input_hash: string;
      output_hash: string | null;
      artifact_ids: string[];
      evidence_count: number;
      verified_evidence_count: number;
      duration_ms: string | null;
      tokens_input: number | null;
      tokens_output: number | null;
      sealed_at: Date;
      metadata: Record<string, unknown>;
    }>(
      `SELECT * FROM terminal_receipts
       WHERE workspace_id = $1
       ORDER BY sealed_at DESC
       LIMIT $2 OFFSET $3`,
      [workspaceId, limit, offset],
    );

    return result.rows.map((row) => this.mapRowToReceipt(row));
  }

  /**
   * List receipts by status
   */
  async listByStatus(
    workspaceId: string,
    status: ReceiptStatus,
    options?: { limit?: number; offset?: number },
  ): Promise<TerminalReceipt[]> {
    const limit = options?.limit ?? 100;
    const offset = options?.offset ?? 0;

    const result = await this.database.query<{
      id: string;
      workspace_id: string;
      run_id: string;
      attempt_id: string;
      status: ReceiptStatus;
      exit_code: number | null;
      input_hash: string;
      output_hash: string | null;
      artifact_ids: string[];
      evidence_count: number;
      verified_evidence_count: number;
      duration_ms: string | null;
      tokens_input: number | null;
      tokens_output: number | null;
      sealed_at: Date;
      metadata: Record<string, unknown>;
    }>(
      `SELECT * FROM terminal_receipts
       WHERE workspace_id = $1 AND status = $2
       ORDER BY sealed_at DESC
       LIMIT $3 OFFSET $4`,
      [workspaceId, status, limit, offset],
    );

    return result.rows.map((row) => this.mapRowToReceipt(row));
  }

  /**
   * Count receipts by status
   */
  async countByStatus(workspaceId: string): Promise<Record<ReceiptStatus, number>> {
    const result = await this.database.query<{
      status: ReceiptStatus;
      count: string;
    }>(
      `SELECT status, COUNT(*) as count
       FROM terminal_receipts
       WHERE workspace_id = $1
       GROUP BY status`,
      [workspaceId],
    );

    const counts: Record<ReceiptStatus, number> = {
      success: 0,
      failure: 0,
      timeout: 0,
      cancelled: 0,
    };

    for (const row of result.rows) {
      counts[row.status] = parseInt(row.count, 10);
    }

    return counts;
  }

  private generateReceiptId(): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 10);
    return `rcpt_${timestamp}${random}`;
  }

  private hashString(content: string): string {
    return createHash("sha256").update(content, "utf-8").digest("hex");
  }

  private hashJson(content: unknown): string {
    return this.hashString(JSON.stringify(content));
  }

  private mapRowToReceipt(row: {
    id: string;
    workspace_id: string;
    run_id: string;
    attempt_id: string;
    status: ReceiptStatus;
    exit_code: number | null;
    input_hash: string;
    output_hash: string | null;
    artifact_ids: string[];
    evidence_count: number;
    verified_evidence_count: number;
    duration_ms: string | null;
    tokens_input: number | null;
    tokens_output: number | null;
    sealed_at: Date;
    metadata: Record<string, unknown>;
  }): TerminalReceipt {
    return {
      id: row.id,
      workspaceId: row.workspace_id,
      runId: row.run_id,
      attemptId: row.attempt_id,
      status: row.status,
      exitCode: row.exit_code,
      inputHash: row.input_hash,
      outputHash: row.output_hash,
      artifactIds: row.artifact_ids,
      evidenceCount: row.evidence_count,
      verifiedEvidenceCount: row.verified_evidence_count,
      durationMs: row.duration_ms === null ? null : Number(row.duration_ms),
      tokensInput: row.tokens_input,
      tokensOutput: row.tokens_output,
      sealedAt: row.sealed_at,
      metadata: row.metadata,
    };
  }
}
