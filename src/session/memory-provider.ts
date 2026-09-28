/**
 * Memory Provider
 * Provider-neutral memory operations with revision control and multi-provider support
 */

/**
 * Memory entry with revision tracking
 */
export interface MemoryEntry {
  id: string;
  workspaceId: string;
  scope: string;
  content: string;
  contentType?: string;
  revision: number;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
  audience?: "user" | "agent" | "system" | "public";
  sensitivity?: "public" | "internal" | "confidential" | "secret";
  retention?: {
    expiresAt?: string;
    policy?: string;
  };
  provenance?: {
    source: string;
    sourceId?: string;
    trustLevel?: "trusted" | "untrusted" | "unknown";
  };
  extraction?: {
    leaseId?: string;
    leasedAt?: string;
    leasedBy?: string;
    leaseExpiresAt?: string;
    lastExtractedAt?: string;
    extractionVersion?: number;
  };
}

/**
 * Memory descriptor
 */
export interface MemoryDescriptor {
  id: string;
  scope: string;
  revision: number;
  size: number;
  createdAt: string;
  updatedAt: string;
  sensitivity?: string;
}

/**
 * Memory search result
 */
export interface MemorySearchResult {
  entry: MemoryEntry;
  score: number;
  excerpt?: string;
}

/**
 * Memory commit request
 */
export interface MemoryCommitRequest {
  workspaceId: string;
  scope: string;
  content: string;
  contentType?: string;
  expectedRevision?: number; // For CAS
  metadata?: Record<string, unknown>;
  audience?: "user" | "agent" | "system" | "public";
  sensitivity?: "public" | "internal" | "confidential" | "secret";
  retention?: {
    expiresAt?: string;
    policy?: string;
  };
  provenance?: {
    source: string;
    sourceId?: string;
    trustLevel?: "trusted" | "untrusted" | "unknown";
  };
  extraction?: {
    leaseId?: string;
    leasedAt?: string;
    leasedBy?: string;
    leaseExpiresAt?: string;
    lastExtractedAt?: string;
    extractionVersion?: number;
  };
}

/**
 * Memory commit result
 */
export interface MemoryCommitResult {
  ok: boolean;
  entry?: MemoryEntry;
  conflictRevision?: number;
  reason?: string;
}

/**
 * Memory export format
 */
export interface MemoryExport {
  version: string;
  exportedAt: string;
  workspaceId: string;
  entries: MemoryEntry[];
  metadata?: Record<string, unknown>;
}

/**
 * Memory import result
 */
export interface MemoryImportResult {
  ok: boolean;
  imported: number;
  skipped: number;
  failed: number;
  errors?: Array<{ id: string; reason: string }>;
}

/**
 * Transaction commit request
 */
export interface MemoryTransactionRequest {
  workspaceId: string;
  commits: MemoryCommitRequest[];
  transactionId?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Transaction commit result
 */
export interface MemoryTransactionResult {
  ok: boolean;
  entries?: MemoryEntry[];
  transactionId?: string;
  partialResults?: Array<{ scope: string; ok: boolean; reason?: string }>;
  reason?: string;
}

/**
 * Credential reference for encrypted storage
 */
export interface CredentialReference {
  type: "encrypted" | "keyring" | "vault";
  keyId: string;
  encryptedValue?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Resolver trust classification
 */
export interface ResolverTrust {
  resolverType: string;
  trustLevel: "trusted" | "untrusted" | "unknown";
  approvedBy?: string;
  approvedAt?: string;
  restrictions?: string[];
}

/**
 * Approval request for sensitive operations
 */
export interface ApprovalRequest {
  id: string;
  operation: "credential_access" | "resolver_use" | "export" | "delete";
  resource: string;
  requestedBy: string;
  requestedAt: string;
  status: "pending" | "approved" | "denied";
  approvedBy?: string;
  approvedAt?: string;
  reason?: string;
}

/**
 * Audit trail entry for memory operations
 */
export interface AuditEntry {
  id: string;
  timestamp: string;
  workspaceId: string;
  operation: "commit" | "edit" | "delete" | "revoke" | "export" | "import";
  actor: string;
  resource: string;
  details?: Record<string, unknown>;
  success: boolean;
  reason?: string;
}

/** Narrow persistence dependency used by the production host MemoryPort. */
export interface MemoryAuditWriter {
  recordAudit(entry: Omit<AuditEntry, "id" | "timestamp">): Promise<AuditEntry>;
}

/**
 * Memory search options
 */
export interface MemorySearchOptions {
  limit?: number;
  offset?: number;
  scope?: string;
  audience?: string[];
  sensitivity?: string[];
  sinceRevision?: number;
  beforeRevision?: number;
  createdAfter?: string;
  createdBefore?: string;
  /**
   * Provenance filters, applied before ranking so untrusted or
   * unexpected sources never reach the scorer.
   */
  provenance?: {
    sources?: string[];
    sourceIds?: string[];
    trustLevels?: Array<"trusted" | "untrusted" | "unknown">;
  };
  extraction?: {
    leaseId?: string;
    leasedAt?: string;
    leasedBy?: string;
    leaseExpiresAt?: string;
    lastExtractedAt?: string;
    extractionVersion?: number;
  };
  /**
   * Temporal cutoff: only revisions created at or before this instant
   * are considered. Entries whose retention has expired by this point
   * are excluded unless includeExpired is set.
   */
  asOf?: string;
  includeExpired?: boolean;
  /**
   * Bounded hybrid search controls. Candidate count is capped before
   * scoring so a large workspace cannot make a query unbounded.
   */
  hybrid?: {
    /** Weight of exact-phrase matching (default 1). */
    phraseWeight?: number;
    /** Weight of distinct query-term overlap (default 0.5). */
    termWeight?: number;
    /** Maximum candidates pulled from storage before ranking (default 500). */
    maxCandidates?: number;
    /** Maximum characters of an entry scanned for term overlap (default 4096). */
    maxScanChars?: number;
  };
}

/**
 * Provider-neutral memory operations
 */
export interface MemoryProvider {
  /**
   * Describe memory entry (metadata only)
   */
  describe(id: string, workspaceId: string): Promise<MemoryDescriptor | null>;

  /**
   * Read memory entry with optional revision
   */
  read(id: string, workspaceId: string, revision?: number): Promise<MemoryEntry | null>;

  /**
   * Search memory entries
   */
  search(
    query: string,
    workspaceId: string,
    options?: MemorySearchOptions,
  ): Promise<MemorySearchResult[]>;

  /**
   * Commit memory entry (create or update with CAS)
   */
  commit(request: MemoryCommitRequest): Promise<MemoryCommitResult>;

  /**
   * Commit multiple entries atomically
   */
  commitTransaction(request: MemoryTransactionRequest): Promise<MemoryTransactionResult>;

  /**
   * Forget memory entry (soft delete)
   */
  forget(id: string, workspaceId: string, reason?: string): Promise<boolean>;

  /**
   * Export memory entries
   */
  export(workspaceId: string, scope?: string): Promise<MemoryExport>;

  /**
   * Import memory entries
   */
  import(data: MemoryExport, workspaceId: string): Promise<MemoryImportResult>;

  /**
   * List memory entries
   */
  list(workspaceId: string, options?: MemorySearchOptions): Promise<MemoryDescriptor[]>;

  /**
   * Get revision history for entry
   */
  getRevisionHistory(id: string, workspaceId: string): Promise<MemoryEntry[]>;

  /**
   * Store encrypted credential reference
   */
  storeCredential(
    scope: string,
    workspaceId: string,
    credential: CredentialReference,
  ): Promise<{ ok: boolean; reason?: string }>;

  /**
   * Retrieve credential reference
   */
  retrieveCredential(scope: string, workspaceId: string): Promise<CredentialReference | null>;

  /**
   * Register resolver trust classification
   */
  registerResolverTrust(
    resolverType: string,
    workspaceId: string,
    trust: ResolverTrust,
  ): Promise<{ ok: boolean; reason?: string }>;

  /**
   * Get resolver trust classification
   */
  getResolverTrust(resolverType: string, workspaceId: string): Promise<ResolverTrust | null>;

  /**
   * Request approval for sensitive operation
   */
  requestApproval(
    request: Omit<ApprovalRequest, "id" | "requestedAt" | "status">,
  ): Promise<ApprovalRequest>;

  /**
   * Approve or deny approval request
   */
  processApproval(
    requestId: string,
    status: "approved" | "denied",
    approvedBy: string,
    reason?: string,
  ): Promise<{ ok: boolean; reason?: string }>;

  /**
   * Get approval request by ID
   */
  getApprovalRequest(requestId: string): Promise<ApprovalRequest | null>;

  /**
   * Acquire extraction lease for background processing
   */
  acquireExtractionLease(
    id: string,
    workspaceId: string,
    leasedBy: string,
    ttlMs?: number,
  ): Promise<{ ok: boolean; leaseId?: string; reason?: string }>;

  /**
   * Release extraction lease
   */
  releaseExtractionLease(
    id: string,
    workspaceId: string,
    leaseId: string,
  ): Promise<{ ok: boolean; reason?: string }>;

  /**
   * Clean up stale extraction leases
   */
  cleanupStaleLeases(workspaceId?: string): Promise<{ cleaned: number }>;

  /**
   * Redact sensitive fields before extraction
   */
  redactForExtraction(entry: MemoryEntry): MemoryEntry;

  /**
   * Record audit trail for memory operation
   */
  recordAudit(entry: Omit<AuditEntry, "id" | "timestamp">): Promise<AuditEntry>;

  /**
   * Query audit trail
   */
  queryAudit(
    workspaceId: string,
    options?: {
      operation?: AuditEntry["operation"];
      actor?: string;
      resource?: string;
      startTime?: string;
      endTime?: string;
      limit?: number;
    },
  ): Promise<AuditEntry[]>;
}

/**
 * In-memory provider implementation
 */
export class InMemoryProvider implements MemoryProvider {
  private entries: Map<string, MemoryEntry[]> = new Map(); // id -> revisions
  private deleted: Set<string> = new Set();
  private credentials: Map<string, CredentialReference> = new Map(); // workspaceId:scope -> credential
  private resolverTrusts: Map<string, ResolverTrust> = new Map(); // workspaceId:resolverType -> trust
  private approvalRequests: Map<string, ApprovalRequest> = new Map();
  private auditLog: AuditEntry[] = []; // requestId -> approval

  async describe(id: string, workspaceId: string): Promise<MemoryDescriptor | null> {
    const entryKey = `${workspaceId}:${id}`;
    if (this.deleted.has(entryKey)) {
      return null;
    }

    const revisions = this.entries.get(entryKey);
    if (!revisions || revisions.length === 0) {
      return null;
    }

    const latest = revisions[revisions.length - 1];

    return {
      id: latest.id,
      scope: latest.scope,
      revision: latest.revision,
      size: Buffer.byteLength(latest.content, "utf8"),
      createdAt: revisions[0].createdAt,
      updatedAt: latest.updatedAt,
      sensitivity: latest.sensitivity,
    };
  }

  async read(id: string, workspaceId: string, revision?: number): Promise<MemoryEntry | null> {
    const entryKey = `${workspaceId}:${id}`;
    if (this.deleted.has(entryKey)) {
      return null;
    }

    const revisions = this.entries.get(entryKey);
    if (!revisions || revisions.length === 0) {
      return null;
    }

    let entry: MemoryEntry;
    if (revision !== undefined) {
      const found = revisions.find((e) => e.revision === revision);
      if (!found) {
        return null;
      }
      entry = found;
    } else {
      entry = revisions[revisions.length - 1];
    }

    return entry;
  }

  async search(
    query: string,
    workspaceId: string,
    options: MemorySearchOptions = {},
  ): Promise<MemorySearchResult[]> {
    const limit = options.limit || 10;
    const offset = options.offset || 0;

    // --- Stage 1: filter before rank ---
    // Every predicate is applied here, on the candidate set, so that
    // nothing excluded by trust, audience or time ever reaches scoring.
    const candidates = Array.from(this.entries.entries())
      .filter(([entryKey, revisions]) => {
        if (this.deleted.has(entryKey)) return false;
        if (revisions.length === 0) return false;
        return true;
      })
      .map(([entryKey, revisions]) => ({
        entryKey,
        revisions,
        entry: this.selectRevision(revisions, options),
      }))
      .filter(
        (c): c is { entryKey: string; revisions: MemoryEntry[]; entry: MemoryEntry } =>
          c.entry !== null,
      )
      .filter(({ entry }) => {
        if (entry.workspaceId !== workspaceId) return false;
        if (options.scope && entry.scope !== options.scope) return false;
        if (options.audience && !options.audience.includes(entry.audience || "public")) {
          return false;
        }
        if (options.sensitivity && !options.sensitivity.includes(entry.sensitivity || "public")) {
          return false;
        }
        if (options.sinceRevision !== undefined && entry.revision < options.sinceRevision) {
          return false;
        }
        if (options.beforeRevision !== undefined && entry.revision >= options.beforeRevision) {
          return false;
        }
        if (!this.matchesProvenance(entry, options.provenance)) return false;
        if (!this.withinTemporalBounds(entry, options)) return false;
        return true;
      })
      .sort((a, b) => {
        if (a.entry.updatedAt !== b.entry.updatedAt) {
          return a.entry.updatedAt < b.entry.updatedAt ? 1 : -1;
        }
        return a.entry.id < b.entry.id ? -1 : a.entry.id > b.entry.id ? 1 : 0;
      });

    // --- Stage 2: bound the candidate set deterministically ---
    const maxCandidates = Math.max(1, options.hybrid?.maxCandidates ?? 500);
    const bounded = candidates.slice(0, maxCandidates);

    // --- Stage 3: rank the bounded set ---
    const results: MemorySearchResult[] = [];
    for (const { entry } of bounded) {
      const score = this.calculateHybridScore(query, entry.content, options.hybrid);
      if (score <= 0) continue;
      results.push({
        entry,
        score,
        excerpt: this.createExcerpt(entry.content, query.toLowerCase()),
      });
    }

    results.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (a.entry.updatedAt !== b.entry.updatedAt) {
        return a.entry.updatedAt < b.entry.updatedAt ? 1 : -1;
      }
      return a.entry.id < b.entry.id ? -1 : a.entry.id > b.entry.id ? 1 : 0;
    });

    return results.slice(offset, offset + limit);
  }

  /**
   * Pick the revision to search over. With an asOf cutoff this is the last
   * revision created at or before that instant; otherwise the latest one.
   */
  private selectRevision(
    revisions: MemoryEntry[],
    options: MemorySearchOptions,
  ): MemoryEntry | null {
    if (!options.asOf) {
      return revisions[revisions.length - 1];
    }

    const cutoff = Date.parse(options.asOf);
    if (Number.isNaN(cutoff)) {
      return revisions[revisions.length - 1];
    }

    let selected: MemoryEntry | null = null;
    for (const revision of revisions) {
      if (Date.parse(revision.updatedAt) <= cutoff) {
        selected = revision;
      } else {
        break;
      }
    }

    return selected;
  }

  private matchesProvenance(
    entry: MemoryEntry,
    filter: MemorySearchOptions["provenance"],
  ): boolean {
    if (!filter) return true;

    if (filter.sources && !filter.sources.includes(entry.provenance?.source ?? "")) {
      return false;
    }
    if (filter.sourceIds && !filter.sourceIds.includes(entry.provenance?.sourceId ?? "")) {
      return false;
    }
    if (
      filter.trustLevels &&
      !filter.trustLevels.includes(entry.provenance?.trustLevel ?? "unknown")
    ) {
      return false;
    }

    return true;
  }

  private withinTemporalBounds(entry: MemoryEntry, options: MemorySearchOptions): boolean {
    const asOf = options.asOf ? Date.parse(options.asOf) : Date.now();
    if (Number.isNaN(asOf)) return true;

    if (options.createdAfter && Date.parse(entry.createdAt) < Date.parse(options.createdAfter)) {
      return false;
    }
    if (options.createdBefore && Date.parse(entry.updatedAt) > Date.parse(options.createdBefore)) {
      return false;
    }

    if (!options.includeExpired && entry.retention?.expiresAt) {
      const expiresAt = Date.parse(entry.retention.expiresAt);
      if (!Number.isNaN(expiresAt) && expiresAt <= asOf) {
        return false;
      }
    }

    return true;
  }

  /**
   * Bounded hybrid score: exact-phrase weight plus distinct-term overlap,
   * with the scanned region capped so cost stays proportional to the bound
   * rather than to document length.
   */
  private calculateHybridScore(
    query: string,
    content: string,
    hybrid?: MemorySearchOptions["hybrid"],
  ): number {
    const queryLower = query.toLowerCase();
    const phraseWeight = hybrid?.phraseWeight ?? 1;
    const termWeight = hybrid?.termWeight ?? 0.5;
    const maxScanChars = Math.max(1, hybrid?.maxScanChars ?? 4096);

    const scanned = content.slice(0, maxScanChars).toLowerCase();
    let score = 0;

    if (queryLower.length > 0) {
      const matches = scanned.split(queryLower).length - 1;
      if (matches > 0) {
        const position = scanned.indexOf(queryLower);
        const positionScore = position === -1 ? 0 : 1 / (position + 1);
        score += (matches + positionScore) * phraseWeight;
      }

      const terms = Array.from(new Set(queryLower.split(/\s+/).filter((t) => t.length > 0)));
      if (terms.length > 1) {
        const hits = terms.filter((term) => scanned.includes(term)).length;
        if (hits > 0) {
          score += (hits / terms.length) * termWeight;
        }
      }
    }

    return score;
  }

  async commit(request: MemoryCommitRequest): Promise<MemoryCommitResult> {
    const entryKey = `${request.workspaceId}:${request.scope}`;
    const existingRevisions = this.entries.get(entryKey);
    const timestamp = new Date().toISOString();

    // CAS check
    if (request.expectedRevision !== undefined) {
      if (!existingRevisions || existingRevisions.length === 0) {
        return {
          ok: false,
          reason: "Entry does not exist but expected revision provided",
        };
      }

      const current = existingRevisions[existingRevisions.length - 1];
      if (current.revision !== request.expectedRevision) {
        return {
          ok: false,
          conflictRevision: current.revision,
          reason: `CAS conflict: expected ${request.expectedRevision}, got ${current.revision}`,
        };
      }
    }

    const newRevision = existingRevisions ? existingRevisions.length + 1 : 1;

    const entry: MemoryEntry = {
      id: request.scope,
      workspaceId: request.workspaceId,
      scope: request.scope,
      content: request.content,
      contentType: request.contentType,
      revision: newRevision,
      createdAt: existingRevisions?.[0]?.createdAt || timestamp,
      updatedAt: timestamp,
      metadata: request.metadata,
      audience: request.audience,
      sensitivity: request.sensitivity,
      retention: request.retention,
      provenance: request.provenance,
    };

    if (existingRevisions) {
      existingRevisions.push(entry);
    } else {
      this.entries.set(entryKey, [entry]);
    }

    // Remove from deleted set if re-creating
    this.deleted.delete(entryKey);

    return { ok: true, entry };
  }

  async commitTransaction(request: MemoryTransactionRequest): Promise<MemoryTransactionResult> {
    const { workspaceId, commits } = request;
    const transactionId =
      request.transactionId || `txn-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    // Validation phase: check all CAS constraints first
    const partialResults: Array<{ scope: string; ok: boolean; reason?: string }> = [];

    for (const commitReq of commits) {
      if (commitReq.expectedRevision !== undefined) {
        const entryKey = `${workspaceId}:${commitReq.scope}`;
        const existingRevisions = this.entries.get(entryKey);

        if (!existingRevisions || existingRevisions.length === 0) {
          return {
            ok: false,
            reason: `Transaction aborted: entry ${commitReq.scope} does not exist but expected revision provided`,
            partialResults,
          };
        }

        const current = existingRevisions[existingRevisions.length - 1];
        if (current.revision !== commitReq.expectedRevision) {
          return {
            ok: false,
            reason: `Transaction aborted: CAS conflict on ${commitReq.scope}: expected ${commitReq.expectedRevision}, got ${current.revision}`,
            partialResults,
          };
        }
      }
    }

    // All validations passed, now commit all entries
    const entries: MemoryEntry[] = [];

    for (const commitReq of commits) {
      const result = await this.commit({
        ...commitReq,
        workspaceId,
      });

      if (result.ok && result.entry) {
        entries.push(result.entry);
        partialResults.push({ scope: commitReq.scope, ok: true });
      } else {
        // This shouldn't happen after validation, but handle it
        partialResults.push({
          scope: commitReq.scope,
          ok: false,
          reason: result.reason || "Unknown error",
        });
      }
    }

    return {
      ok: true,
      entries,
      transactionId,
      partialResults,
    };
  }

  async forget(id: string, workspaceId: string, _reason?: string): Promise<boolean> {
    const entryKey = `${workspaceId}:${id}`;
    const revisions = this.entries.get(entryKey);
    if (!revisions || revisions.length === 0) {
      return false;
    }

    this.deleted.add(entryKey);
    return true;
  }

  async export(workspaceId: string, scope?: string): Promise<MemoryExport> {
    const entries: MemoryEntry[] = [];

    for (const [entryKey, revisions] of this.entries) {
      if (this.deleted.has(entryKey)) continue;
      if (revisions.length === 0) continue;

      const latest = revisions[revisions.length - 1];
      if (latest.workspaceId !== workspaceId) continue;
      if (scope && latest.scope !== scope) continue;

      entries.push(latest);
    }

    return {
      version: "v1",
      exportedAt: new Date().toISOString(),
      workspaceId,
      entries,
    };
  }

  async import(data: MemoryExport, workspaceId: string): Promise<MemoryImportResult> {
    let imported = 0;
    let skipped = 0;
    let failed = 0;
    const errors: Array<{ id: string; reason: string }> = [];

    for (const entry of data.entries) {
      try {
        // Override workspace ID for import
        const result = await this.commit({
          workspaceId,
          scope: entry.scope,
          content: entry.content,
          contentType: entry.contentType,
          metadata: entry.metadata,
          audience: entry.audience,
          sensitivity: entry.sensitivity,
          retention: entry.retention,
          provenance: entry.provenance,
        });

        if (result.ok) {
          imported++;
        } else {
          skipped++;
        }
      } catch (error) {
        failed++;
        errors.push({
          id: entry.id,
          reason: error instanceof Error ? error.message : String(error),
        });
      }
    }

    return {
      ok: failed === 0,
      imported,
      skipped,
      failed,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  async list(workspaceId: string, options: MemorySearchOptions = {}): Promise<MemoryDescriptor[]> {
    const descriptors: MemoryDescriptor[] = [];

    for (const [entryKey, revisions] of this.entries) {
      if (this.deleted.has(entryKey)) continue;
      if (revisions.length === 0) continue;

      const latest = revisions[revisions.length - 1];
      if (latest.workspaceId !== workspaceId) continue;
      if (options.scope && latest.scope !== options.scope) continue;

      const descriptor = await this.describe(latest.id, workspaceId);
      if (descriptor) {
        descriptors.push(descriptor);
      }
    }

    return descriptors;
  }

  async getRevisionHistory(id: string, workspaceId: string): Promise<MemoryEntry[]> {
    const entryKey = `${workspaceId}:${id}`;
    if (this.deleted.has(entryKey)) {
      return [];
    }

    const revisions = this.entries.get(entryKey);
    if (!revisions || revisions.length === 0) {
      return [];
    }

    return revisions;
  }

  async storeCredential(
    scope: string,
    workspaceId: string,
    credential: CredentialReference,
  ): Promise<{ ok: boolean; reason?: string }> {
    const credentialKey = `${workspaceId}:${scope}`;
    this.credentials.set(credentialKey, credential);
    return { ok: true };
  }

  async retrieveCredential(
    scope: string,
    workspaceId: string,
  ): Promise<CredentialReference | null> {
    const credentialKey = `${workspaceId}:${scope}`;
    return this.credentials.get(credentialKey) || null;
  }

  async registerResolverTrust(
    resolverType: string,
    workspaceId: string,
    trust: ResolverTrust,
  ): Promise<{ ok: boolean; reason?: string }> {
    const trustKey = `${workspaceId}:${resolverType}`;
    this.resolverTrusts.set(trustKey, trust);
    return { ok: true };
  }

  async getResolverTrust(resolverType: string, workspaceId: string): Promise<ResolverTrust | null> {
    const trustKey = `${workspaceId}:${resolverType}`;
    return this.resolverTrusts.get(trustKey) || null;
  }

  async requestApproval(
    request: Omit<ApprovalRequest, "id" | "requestedAt" | "status">,
  ): Promise<ApprovalRequest> {
    const approval: ApprovalRequest = {
      id: `approval-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      ...request,
      requestedAt: new Date().toISOString(),
      status: "pending",
    };

    this.approvalRequests.set(approval.id, approval);
    return approval;
  }

  async processApproval(
    requestId: string,
    status: "approved" | "denied",
    approvedBy: string,
    reason?: string,
  ): Promise<{ ok: boolean; reason?: string }> {
    const approval = this.approvalRequests.get(requestId);

    if (!approval) {
      return { ok: false, reason: "Approval request not found" };
    }

    if (approval.status !== "pending") {
      return { ok: false, reason: `Approval already ${approval.status}` };
    }

    approval.status = status;
    approval.approvedBy = approvedBy;
    approval.approvedAt = new Date().toISOString();
    if (reason) {
      approval.reason = reason;
    }

    this.approvalRequests.set(requestId, approval);
    return { ok: true };
  }

  async getApprovalRequest(requestId: string): Promise<ApprovalRequest | null> {
    return this.approvalRequests.get(requestId) || null;
  }

  async acquireExtractionLease(
    id: string,
    workspaceId: string,
    leasedBy: string,
    ttlMs: number = 300000, // 5 minutes default
  ): Promise<{ ok: boolean; leaseId?: string; reason?: string }> {
    const entryKey = `${workspaceId}:${id}`;
    const revisions = this.entries.get(entryKey);

    if (!revisions || revisions.length === 0 || this.deleted.has(entryKey)) {
      return { ok: false, reason: "Entry not found" };
    }

    const latest = revisions[revisions.length - 1];

    // Check for existing valid lease
    if (latest.extraction?.leaseId && latest.extraction.leaseExpiresAt) {
      const expiresAt = Date.parse(latest.extraction.leaseExpiresAt);
      if (!Number.isNaN(expiresAt) && expiresAt > Date.now()) {
        return {
          ok: false,
          reason: `Entry already leased until ${latest.extraction.leaseExpiresAt}`,
        };
      }
    }

    // Acquire new lease
    const leaseId = `lease-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const now = new Date();
    const leaseExpiresAt = new Date(now.getTime() + ttlMs).toISOString();

    latest.extraction = {
      leaseId,
      leasedAt: now.toISOString(),
      leasedBy,
      leaseExpiresAt,
      lastExtractedAt: latest.extraction?.lastExtractedAt,
      extractionVersion: latest.extraction?.extractionVersion,
    };

    return { ok: true, leaseId };
  }

  async releaseExtractionLease(
    id: string,
    workspaceId: string,
    leaseId: string,
  ): Promise<{ ok: boolean; reason?: string }> {
    const entryKey = `${workspaceId}:${id}`;
    const revisions = this.entries.get(entryKey);

    if (!revisions || revisions.length === 0) {
      return { ok: false, reason: "Entry not found" };
    }

    const latest = revisions[revisions.length - 1];

    if (!latest.extraction?.leaseId) {
      return { ok: false, reason: "No active lease" };
    }

    if (latest.extraction.leaseId !== leaseId) {
      return { ok: false, reason: "Lease ID mismatch" };
    }

    // Mark extraction as complete and clear lease
    latest.extraction = {
      lastExtractedAt: new Date().toISOString(),
      extractionVersion: (latest.extraction.extractionVersion || 0) + 1,
    };

    return { ok: true };
  }

  async cleanupStaleLeases(workspaceId?: string): Promise<{ cleaned: number }> {
    let cleaned = 0;
    const now = Date.now();

    for (const [entryKey, revisions] of this.entries) {
      if (this.deleted.has(entryKey)) continue;
      if (revisions.length === 0) continue;

      const latest = revisions[revisions.length - 1];

      // Skip if workspace filter doesn't match
      if (workspaceId && latest.workspaceId !== workspaceId) continue;

      // Check if lease is stale
      if (latest.extraction?.leaseId && latest.extraction.leaseExpiresAt) {
        const expiresAt = Date.parse(latest.extraction.leaseExpiresAt);
        if (!Number.isNaN(expiresAt) && expiresAt <= now) {
          // Clear stale lease
          latest.extraction = {
            lastExtractedAt: latest.extraction.lastExtractedAt,
            extractionVersion: latest.extraction.extractionVersion,
          };
          cleaned++;
        }
      }
    }

    return { cleaned };
  }

  redactForExtraction(entry: MemoryEntry): MemoryEntry {
    // Create a shallow copy with sensitive fields redacted
    const redacted: MemoryEntry = { ...entry };

    // Redact credential references in metadata
    if (redacted.metadata) {
      redacted.metadata = { ...redacted.metadata };
      for (const [key, value] of Object.entries(redacted.metadata)) {
        if (
          typeof value === "string" &&
          (key.toLowerCase().includes("password") ||
            key.toLowerCase().includes("secret") ||
            key.toLowerCase().includes("token") ||
            key.toLowerCase().includes("key"))
        ) {
          redacted.metadata[key] = "[REDACTED]";
        }
      }
    }

    // Redact PII patterns in content (basic patterns)
    if (redacted.content) {
      let content = redacted.content;

      // Email addresses
      content = content.replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, "[EMAIL]");

      // Phone numbers (simple patterns)
      content = content.replace(/\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/g, "[PHONE]");

      // Credit card patterns (simple)
      content = content.replace(/\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b/g, "[CARD]");

      // SSN patterns
      content = content.replace(/\b\d{3}-\d{2}-\d{4}\b/g, "[SSN]");

      redacted.content = content;
    }

    return redacted;
  }

  async recordAudit(entry: Omit<AuditEntry, "id" | "timestamp">): Promise<AuditEntry> {
    const auditEntry: AuditEntry = {
      id: `audit-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      timestamp: new Date().toISOString(),
      ...entry,
    };

    this.auditLog.push(auditEntry);
    return auditEntry;
  }

  async queryAudit(
    workspaceId: string,
    options: {
      operation?: AuditEntry["operation"];
      actor?: string;
      resource?: string;
      startTime?: string;
      endTime?: string;
      limit?: number;
    } = {},
  ): Promise<AuditEntry[]> {
    let results = this.auditLog.filter((entry) => entry.workspaceId === workspaceId);

    if (options.operation) {
      results = results.filter((entry) => entry.operation === options.operation);
    }

    if (options.actor) {
      results = results.filter((entry) => entry.actor === options.actor);
    }

    if (options.resource !== undefined) {
      results = results.filter((entry) => entry.resource === options.resource);
    }

    if (options.startTime) {
      const start = Date.parse(options.startTime);
      if (!Number.isNaN(start)) {
        results = results.filter((entry) => Date.parse(entry.timestamp) >= start);
      }
    }

    if (options.endTime) {
      const end = Date.parse(options.endTime);
      if (!Number.isNaN(end)) {
        results = results.filter((entry) => Date.parse(entry.timestamp) <= end);
      }
    }

    // Sort by timestamp descending (most recent first)
    results.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));

    const limit = options.limit || 100;
    return results.slice(0, limit);
  }

  // Helper methods

  private createExcerpt(content: string, query: string, contextChars: number = 100): string {
    const index = content.toLowerCase().indexOf(query);
    if (index === -1) {
      return content.slice(0, contextChars);
    }

    const start = Math.max(0, index - contextChars / 2);
    const end = Math.min(content.length, index + query.length + contextChars / 2);

    let excerpt = content.slice(start, end);
    if (start > 0) excerpt = `...${excerpt}`;
    if (end < content.length) excerpt = `${excerpt}...`;

    return excerpt;
  }

  // Test utilities

  clear(): void {
    this.entries.clear();
    this.deleted.clear();
    this.credentials.clear();
    this.resolverTrusts.clear();
    this.approvalRequests.clear();
  }

  size(): number {
    return this.entries.size - this.deleted.size;
  }

  // Internal methods for LocalProvider direct state restoration
  _loadRevisions(workspaceId: string, scope: string, revisions: MemoryEntry[]): void {
    const entryKey = `${workspaceId}:${scope}`;
    this.entries.set(entryKey, revisions);
  }

  _loadApprovalDirect(approval: ApprovalRequest): void {
    this.approvalRequests.set(approval.id, approval);
  }
}

/**
 * Local file-based provider with deterministic storage
 */
export class LocalProvider implements MemoryProvider {
  private baseDir: string;
  private inMemory: InMemoryProvider;

  constructor(baseDir: string) {
    this.baseDir = baseDir;
    this.inMemory = new InMemoryProvider();
  }

  private getWorkspaceDir(workspaceId: string): string {
    return `${this.baseDir}/${workspaceId}`;
  }

  private getEntryPath(workspaceId: string, scope: string): string {
    return `${this.getWorkspaceDir(workspaceId)}/entries/${scope}.json`;
  }

  private getCredentialPath(workspaceId: string, scope: string): string {
    return `${this.getWorkspaceDir(workspaceId)}/credentials/${scope}.json`;
  }

  private getResolverPath(workspaceId: string, resolverType: string): string {
    return `${this.getWorkspaceDir(workspaceId)}/resolvers/${resolverType}.json`;
  }

  private getApprovalPath(requestId: string): string {
    return `${this.baseDir}/approvals/${requestId}.json`;
  }

  private getAuditPath(workspaceId: string): string {
    return `${this.getWorkspaceDir(workspaceId)}/audit.jsonl`;
  }

  async describe(id: string, workspaceId: string): Promise<MemoryDescriptor | null> {
    await this.loadEntry(id, workspaceId);
    return this.inMemory.describe(id, workspaceId);
  }

  async read(id: string, workspaceId: string, revision?: number): Promise<MemoryEntry | null> {
    await this.loadEntry(id, workspaceId);
    return this.inMemory.read(id, workspaceId, revision);
  }

  async search(
    query: string,
    workspaceId: string,
    options?: MemorySearchOptions,
  ): Promise<MemorySearchResult[]> {
    await this.loadWorkspace(workspaceId);
    return this.inMemory.search(query, workspaceId, options);
  }

  async commit(request: MemoryCommitRequest): Promise<MemoryCommitResult> {
    await this.loadEntry(request.scope, request.workspaceId);
    const result = await this.inMemory.commit(request);

    if (result.ok && result.entry) {
      await this.saveEntry(result.entry);
    }

    return result;
  }

  async commitTransaction(request: MemoryTransactionRequest): Promise<MemoryTransactionResult> {
    // Load all entries involved in transaction
    for (const commit of request.commits) {
      await this.loadEntry(commit.scope, request.workspaceId);
    }

    const result = await this.inMemory.commitTransaction(request);

    if (result.ok && result.entries) {
      for (const entry of result.entries) {
        await this.saveEntry(entry);
      }
    }

    return result;
  }

  async forget(id: string, workspaceId: string, reason?: string): Promise<boolean> {
    await this.loadEntry(id, workspaceId);
    const result = await this.inMemory.forget(id, workspaceId, reason);

    if (result) {
      await this.deleteEntry(id, workspaceId);
    }

    return result;
  }

  async export(workspaceId: string, scope?: string): Promise<MemoryExport> {
    await this.loadWorkspace(workspaceId);
    return this.inMemory.export(workspaceId, scope);
  }

  async import(data: MemoryExport, workspaceId: string): Promise<MemoryImportResult> {
    const result = await this.inMemory.import(data, workspaceId);

    // Save all imported entries
    const exported = await this.inMemory.export(workspaceId);
    for (const entry of exported.entries) {
      await this.saveEntry(entry);
    }

    return result;
  }

  async list(workspaceId: string, options?: MemorySearchOptions): Promise<MemoryDescriptor[]> {
    await this.loadWorkspace(workspaceId);
    return this.inMemory.list(workspaceId, options);
  }

  async getRevisionHistory(id: string, workspaceId: string): Promise<MemoryEntry[]> {
    await this.loadEntry(id, workspaceId);
    return this.inMemory.getRevisionHistory(id, workspaceId);
  }

  async storeCredential(
    scope: string,
    workspaceId: string,
    credential: CredentialReference,
  ): Promise<{ ok: boolean; reason?: string }> {
    const result = await this.inMemory.storeCredential(scope, workspaceId, credential);

    if (result.ok) {
      await this.saveCredential(scope, workspaceId, credential);
    }

    return result;
  }

  async retrieveCredential(
    scope: string,
    workspaceId: string,
  ): Promise<CredentialReference | null> {
    await this.loadCredential(scope, workspaceId);
    return this.inMemory.retrieveCredential(scope, workspaceId);
  }

  async registerResolverTrust(
    resolverType: string,
    workspaceId: string,
    trust: ResolverTrust,
  ): Promise<{ ok: boolean; reason?: string }> {
    const result = await this.inMemory.registerResolverTrust(resolverType, workspaceId, trust);

    if (result.ok) {
      await this.saveResolverTrust(resolverType, workspaceId, trust);
    }

    return result;
  }

  async getResolverTrust(resolverType: string, workspaceId: string): Promise<ResolverTrust | null> {
    await this.loadResolverTrust(resolverType, workspaceId);
    return this.inMemory.getResolverTrust(resolverType, workspaceId);
  }

  async requestApproval(
    request: Omit<ApprovalRequest, "id" | "requestedAt" | "status">,
  ): Promise<ApprovalRequest> {
    const approval = await this.inMemory.requestApproval(request);
    await this.saveApproval(approval);
    return approval;
  }

  async processApproval(
    requestId: string,
    status: "approved" | "denied",
    approvedBy: string,
    reason?: string,
  ): Promise<{ ok: boolean; reason?: string }> {
    await this.loadApproval(requestId);
    const result = await this.inMemory.processApproval(requestId, status, approvedBy, reason);

    if (result.ok) {
      const approval = await this.inMemory.getApprovalRequest(requestId);
      if (approval) {
        await this.saveApproval(approval);
      }
    }

    return result;
  }

  async getApprovalRequest(requestId: string): Promise<ApprovalRequest | null> {
    await this.loadApproval(requestId);
    return this.inMemory.getApprovalRequest(requestId);
  }

  async acquireExtractionLease(
    id: string,
    workspaceId: string,
    leasedBy: string,
    ttlMs?: number,
  ): Promise<{ ok: boolean; leaseId?: string; reason?: string }> {
    await this.loadEntry(id, workspaceId);
    const result = await this.inMemory.acquireExtractionLease(id, workspaceId, leasedBy, ttlMs);

    if (result.ok) {
      const entry = await this.inMemory.read(id, workspaceId);
      if (entry) {
        await this.saveEntry(entry);
      }
    }

    return result;
  }

  async releaseExtractionLease(
    id: string,
    workspaceId: string,
    leaseId: string,
  ): Promise<{ ok: boolean; reason?: string }> {
    await this.loadEntry(id, workspaceId);
    const result = await this.inMemory.releaseExtractionLease(id, workspaceId, leaseId);

    if (result.ok) {
      const entry = await this.inMemory.read(id, workspaceId);
      if (entry) {
        await this.saveEntry(entry);
      }
    }

    return result;
  }

  async cleanupStaleLeases(workspaceId?: string): Promise<{ cleaned: number }> {
    if (workspaceId) {
      await this.loadWorkspace(workspaceId);
    }
    return this.inMemory.cleanupStaleLeases(workspaceId);
  }

  redactForExtraction(entry: MemoryEntry): MemoryEntry {
    return this.inMemory.redactForExtraction(entry);
  }

  async recordAudit(entry: Omit<AuditEntry, "id" | "timestamp">): Promise<AuditEntry> {
    const auditEntry = await this.inMemory.recordAudit(entry);
    await this.appendAuditEntry(entry.workspaceId, auditEntry);
    return auditEntry;
  }

  async queryAudit(
    workspaceId: string,
    options: {
      operation?: AuditEntry["operation"];
      actor?: string;
      resource?: string;
      startTime?: string;
      endTime?: string;
      limit?: number;
    } = {},
  ): Promise<AuditEntry[]> {
    await this.loadAuditLog(workspaceId);
    return this.inMemory.queryAudit(workspaceId, options);
  }

  // Private helper methods for file I/O

  private async loadEntry(id: string, workspaceId: string): Promise<void> {
    const entryPath = this.getEntryPath(workspaceId, id);

    try {
      const fs = await import("node:fs/promises");
      const content = await fs.readFile(entryPath, "utf-8");
      const revisions: MemoryEntry[] = JSON.parse(content);

      // Directly load revisions without re-committing
      this.inMemory._loadRevisions(workspaceId, id, revisions);
    } catch (error: unknown) {
      // File doesn't exist yet, that's ok
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async loadWorkspace(workspaceId: string): Promise<void> {
    const workspaceDir = `${this.getWorkspaceDir(workspaceId)}/entries`;

    try {
      const fs = await import("node:fs/promises");
      const files = await fs.readdir(workspaceDir);

      for (const file of files) {
        if (file.endsWith(".json")) {
          const scope = file.replace(".json", "");
          await this.loadEntry(scope, workspaceId);
        }
      }
    } catch (error: unknown) {
      // Directory doesn't exist yet, that's ok
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async saveEntry(entry: MemoryEntry): Promise<void> {
    const entryPath = this.getEntryPath(entry.workspaceId, entry.scope);
    const fs = await import("node:fs/promises");

    // Ensure directory exists
    const dir = entryPath.substring(0, entryPath.lastIndexOf("/"));
    await fs.mkdir(dir, { recursive: true });

    // Get all revisions and save
    const revisions = await this.inMemory.getRevisionHistory(entry.id, entry.workspaceId);
    await fs.writeFile(entryPath, JSON.stringify(revisions, null, 2), "utf-8");
  }

  private async deleteEntry(id: string, workspaceId: string): Promise<void> {
    const entryPath = this.getEntryPath(workspaceId, id);

    try {
      const fs = await import("node:fs/promises");
      await fs.unlink(entryPath);
    } catch (error: unknown) {
      // File doesn't exist, that's ok
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async loadCredential(scope: string, workspaceId: string): Promise<void> {
    const credPath = this.getCredentialPath(workspaceId, scope);

    try {
      const fs = await import("node:fs/promises");
      const content = await fs.readFile(credPath, "utf-8");
      const credential: CredentialReference = JSON.parse(content);
      await this.inMemory.storeCredential(scope, workspaceId, credential);
    } catch (error: unknown) {
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async saveCredential(
    scope: string,
    workspaceId: string,
    credential: CredentialReference,
  ): Promise<void> {
    const credPath = this.getCredentialPath(workspaceId, scope);
    const fs = await import("node:fs/promises");

    const dir = credPath.substring(0, credPath.lastIndexOf("/"));
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(credPath, JSON.stringify(credential, null, 2), "utf-8");
  }

  private async loadResolverTrust(resolverType: string, workspaceId: string): Promise<void> {
    const trustPath = this.getResolverPath(workspaceId, resolverType);

    try {
      const fs = await import("node:fs/promises");
      const content = await fs.readFile(trustPath, "utf-8");
      const trust: ResolverTrust = JSON.parse(content);
      await this.inMemory.registerResolverTrust(resolverType, workspaceId, trust);
    } catch (error: unknown) {
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async saveResolverTrust(
    resolverType: string,
    workspaceId: string,
    trust: ResolverTrust,
  ): Promise<void> {
    const trustPath = this.getResolverPath(workspaceId, resolverType);
    const fs = await import("node:fs/promises");

    const dir = trustPath.substring(0, trustPath.lastIndexOf("/"));
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(trustPath, JSON.stringify(trust, null, 2), "utf-8");
  }

  private async loadApproval(requestId: string): Promise<void> {
    const approvalPath = this.getApprovalPath(requestId);

    try {
      const fs = await import("node:fs/promises");
      const content = await fs.readFile(approvalPath, "utf-8");
      const approval: ApprovalRequest = JSON.parse(content);

      // Directly load approval without creating new request
      this.inMemory._loadApprovalDirect(approval);
    } catch (error: unknown) {
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async saveApproval(approval: ApprovalRequest): Promise<void> {
    const approvalPath = this.getApprovalPath(approval.id);
    const fs = await import("node:fs/promises");

    const dir = approvalPath.substring(0, approvalPath.lastIndexOf("/"));
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(approvalPath, JSON.stringify(approval, null, 2), "utf-8");
  }

  private async loadAuditLog(workspaceId: string): Promise<void> {
    const auditPath = this.getAuditPath(workspaceId);

    try {
      const fs = await import("node:fs/promises");
      const content = await fs.readFile(auditPath, "utf-8");
      const lines = content.trim().split("\n");

      for (const line of lines) {
        if (line.trim()) {
          const auditEntry: AuditEntry = JSON.parse(line);
          await this.inMemory.recordAudit({
            workspaceId: auditEntry.workspaceId,
            operation: auditEntry.operation,
            actor: auditEntry.actor,
            resource: auditEntry.resource,
            details: auditEntry.details,
            success: auditEntry.success,
            reason: auditEntry.reason,
          });
        }
      }
    } catch (error: unknown) {
      if (error && typeof error === "object" && "code" in error && error.code !== "ENOENT") {
        throw error;
      }
    }
  }

  private async appendAuditEntry(workspaceId: string, entry: AuditEntry): Promise<void> {
    const auditPath = this.getAuditPath(workspaceId);
    const fs = await import("node:fs/promises");

    const dir = auditPath.substring(0, auditPath.lastIndexOf("/"));
    await fs.mkdir(dir, { recursive: true });

    await fs.appendFile(auditPath, `${JSON.stringify(entry)}\n`, "utf-8");
  }
}
