/**
 * Compaction Coordinator
 * Manages compaction cursor with contiguous check, CAS, lease/heartbeat/retry/gap behavior
 */

import type { SessionTree } from "./session-tree.js";

/**
 * Compaction cursor state
 */
export interface CompactionCursor {
  sessionId: string;
  cursor: string;
  compactedUpTo: number;
  timestamp: string;
  leaseHolder: string | null;
  leaseExpiry: string | null;
  version: number;
}

/**
 * Compaction lease
 */
export interface CompactionLease {
  sessionId: string;
  leaseId: string;
  holder: string;
  acquiredAt: string;
  expiresAt: string;
  heartbeatIntervalMs: number;
}

/**
 * Compaction result
 */
export interface CompactionResult {
  ok: boolean;
  cursor?: string;
  compactedUpTo?: number;
  reason?: string;
  gaps?: number[];
  shouldRetry?: boolean;
}

/**
 * CAS operation result
 */
export interface CasResult<T> {
  ok: boolean;
  value?: T;
  currentVersion?: number;
  reason?: string;
}

/**
 * Compaction coordinator with CAS and lease management
 */
export class CompactionCoordinator {
  private cursors: Map<string, CompactionCursor> = new Map();
  private leases: Map<string, CompactionLease> = new Map();
  private heartbeatTimers: Map<string, NodeJS.Timeout> = new Map();

  constructor(
    private readonly defaultLeaseMs: number = 30000,
    private readonly heartbeatIntervalMs: number = 10000,
  ) {
    if (defaultLeaseMs <= heartbeatIntervalMs) {
      throw new Error("Lease duration must be greater than heartbeat interval");
    }
  }

  /**
   * Acquire compaction lease with CAS
   */
  async acquireLease(sessionId: string, holder: string): Promise<CasResult<CompactionLease>> {
    const existing = this.leases.get(sessionId);

    // Check if lease exists and is still valid
    if (existing) {
      const now = this.getCurrentTime();
      const expiresAt = new Date(existing.expiresAt).getTime();

      if (now < expiresAt) {
        // Lease is still held by someone
        if (existing.holder === holder) {
          // Same holder, extend the lease
          return this.extendLease(sessionId, holder);
        }

        return {
          ok: false,
          reason: `Lease held by ${existing.holder} until ${existing.expiresAt}`,
        };
      }

      // Lease expired, can acquire
    }

    // Create new lease
    const leaseId = this.generateLeaseId();
    const now = this.getCurrentTime();
    const expiresAt = now + this.defaultLeaseMs;

    const lease: CompactionLease = {
      sessionId,
      leaseId,
      holder,
      acquiredAt: new Date(now).toISOString(),
      expiresAt: new Date(expiresAt).toISOString(),
      heartbeatIntervalMs: this.heartbeatIntervalMs,
    };

    this.leases.set(sessionId, lease);

    // Start heartbeat
    this.startHeartbeat(sessionId, holder);

    return {
      ok: true,
      value: lease,
    };
  }

  /**
   * Extend lease (renew)
   */
  private extendLease(sessionId: string, holder: string): CasResult<CompactionLease> {
    const existing = this.leases.get(sessionId);

    if (!existing || existing.holder !== holder) {
      return {
        ok: false,
        reason: "Not the lease holder",
      };
    }

    const now = this.getCurrentTime();
    const expiresAt = now + this.defaultLeaseMs;

    const updated: CompactionLease = {
      ...existing,
      expiresAt: new Date(expiresAt).toISOString(),
    };

    this.leases.set(sessionId, updated);

    return {
      ok: true,
      value: updated,
    };
  }

  /**
   * Release lease
   */
  async releaseLease(sessionId: string, holder: string): Promise<{ ok: boolean }> {
    const lease = this.leases.get(sessionId);

    if (!lease) {
      return { ok: true }; // Already released
    }

    if (lease.holder !== holder) {
      return { ok: false };
    }

    this.leases.delete(sessionId);
    this.stopHeartbeat(sessionId);

    return { ok: true };
  }

  /**
   * Start heartbeat for lease
   */
  private startHeartbeat(sessionId: string, holder: string): void {
    this.stopHeartbeat(sessionId);

    const timer = setInterval(() => {
      this.sendHeartbeat(sessionId, holder);
    }, this.heartbeatIntervalMs);
    // A leaked lease must never keep the process alive.
    timer.unref?.();

    this.heartbeatTimers.set(sessionId, timer);
  }

  /**
   * Stop heartbeat
   */
  private stopHeartbeat(sessionId: string): void {
    const timer = this.heartbeatTimers.get(sessionId);
    if (timer) {
      clearInterval(timer);
      this.heartbeatTimers.delete(sessionId);
    }
  }

  /**
   * Send heartbeat to keep lease alive
   */
  private sendHeartbeat(sessionId: string, holder: string): void {
    const lease = this.leases.get(sessionId);

    if (!lease || lease.holder !== holder) {
      this.stopHeartbeat(sessionId);
      return;
    }

    // Extend lease
    this.extendLease(sessionId, holder);
  }

  /**
   * Get current cursor with CAS
   */
  getCursor(sessionId: string): CompactionCursor | undefined {
    return this.cursors.get(sessionId);
  }

  /**
   * Update cursor with CAS (Compare-And-Swap)
   */
  updateCursor(
    sessionId: string,
    newCursor: string,
    newCompactedUpTo: number,
    expectedVersion: number | null,
    holder: string,
  ): CasResult<CompactionCursor> {
    const current = this.cursors.get(sessionId);

    // Verify lease
    const lease = this.leases.get(sessionId);
    if (!lease || lease.holder !== holder) {
      return {
        ok: false,
        reason: "Not the lease holder",
      };
    }

    // Check lease not expired
    const now = this.getCurrentTime();
    const expiresAt = new Date(lease.expiresAt).getTime();
    if (now >= expiresAt) {
      return {
        ok: false,
        reason: "Lease expired",
      };
    }

    // CAS check
    if (current) {
      if (expectedVersion === null) {
        return {
          ok: false,
          currentVersion: current.version,
          reason: "Cursor exists but expected null version",
        };
      }

      if (current.version !== expectedVersion) {
        return {
          ok: false,
          currentVersion: current.version,
          reason: `Version mismatch: expected ${expectedVersion}, got ${current.version}`,
        };
      }

      // Monotonicity check
      if (newCompactedUpTo < current.compactedUpTo) {
        return {
          ok: false,
          currentVersion: current.version,
          reason: `Cannot move cursor backward: ${newCompactedUpTo} < ${current.compactedUpTo}`,
        };
      }
    } else if (expectedVersion !== null) {
      return {
        ok: false,
        currentVersion: 0,
        reason: "Cursor does not exist but expected version provided",
      };
    }

    // Update cursor
    const newVersion = current ? current.version + 1 : 1;
    const updated: CompactionCursor = {
      sessionId,
      cursor: newCursor,
      compactedUpTo: newCompactedUpTo,
      timestamp: new Date().toISOString(),
      leaseHolder: holder,
      leaseExpiry: lease.expiresAt,
      version: newVersion,
    };

    this.cursors.set(sessionId, updated);

    return {
      ok: true,
      value: updated,
      currentVersion: newVersion,
    };
  }

  /**
   * Verify contiguous sequence and detect gaps
   */
  verifyContiguous(
    tree: SessionTree,
    fromSeq: number,
    toSeq: number,
  ): { ok: boolean; gaps: number[] } {
    const gaps: number[] = [];

    for (let seq = fromSeq; seq <= toSeq; seq++) {
      const entry = tree.getEntryBySeq(seq);
      if (!entry) {
        gaps.push(seq);
      }
    }

    return {
      ok: gaps.length === 0,
      gaps,
    };
  }

  /**
   * Attempt compaction with retry
   */
  async attemptCompaction(
    tree: SessionTree,
    sessionId: string,
    targetSeq: number,
    holder: string,
    maxRetries: number = 3,
  ): Promise<CompactionResult> {
    let retries = 0;

    while (retries < maxRetries) {
      const result = await this.tryCompaction(tree, sessionId, targetSeq, holder);

      if (result.ok) {
        return result;
      }

      if (!result.shouldRetry) {
        return result;
      }

      retries++;

      // Exponential backoff
      if (retries < maxRetries) {
        await this.sleep(2 ** retries * 100);
      }
    }

    return {
      ok: false,
      reason: `Max retries (${maxRetries}) exceeded`,
      shouldRetry: false,
    };
  }

  /**
   * Try compaction once
   */
  private async tryCompaction(
    tree: SessionTree,
    sessionId: string,
    targetSeq: number,
    holder: string,
  ): Promise<CompactionResult> {
    // Acquire lease
    const leaseResult = await this.acquireLease(sessionId, holder);
    if (!leaseResult.ok) {
      return {
        ok: false,
        reason: leaseResult.reason,
        shouldRetry: true,
      };
    }

    try {
      // Get current cursor
      const currentCursor = this.getCursor(sessionId);
      const fromSeq = currentCursor ? currentCursor.compactedUpTo + 1 : 1;

      // Verify contiguous
      const verification = this.verifyContiguous(tree, fromSeq, targetSeq);
      if (!verification.ok) {
        return {
          ok: false,
          gaps: verification.gaps,
          reason: `Gaps detected in sequence ${fromSeq}-${targetSeq}: ${verification.gaps.join(", ")}`,
          shouldRetry: false,
        };
      }

      // Generate new cursor
      const newCursor = this.generateCursor(sessionId, targetSeq);

      // Update cursor with CAS
      const expectedVersion = currentCursor ? currentCursor.version : null;
      const casResult = this.updateCursor(sessionId, newCursor, targetSeq, expectedVersion, holder);

      if (!casResult.ok) {
        return {
          ok: false,
          reason: casResult.reason,
          shouldRetry: true,
        };
      }

      return {
        ok: true,
        cursor: newCursor,
        compactedUpTo: targetSeq,
      };
    } finally {
      // Release lease
      await this.releaseLease(sessionId, holder);
    }
  }

  /**
   * Handle gap behavior
   */
  handleGaps(gaps: number[], strategy: "fail" | "skip" | "wait"): { ok: boolean; action: string } {
    if (gaps.length === 0) {
      return { ok: true, action: "none" };
    }

    switch (strategy) {
      case "fail":
        return {
          ok: false,
          action: `Fail compaction due to ${gaps.length} gap(s): ${gaps.join(", ")}`,
        };

      case "skip":
        return {
          ok: true,
          action: `Skip gaps and compact up to ${gaps[0] - 1}`,
        };

      case "wait":
        return {
          ok: false,
          action: `Wait for gaps to be filled: ${gaps.join(", ")}`,
        };

      default:
        return { ok: false, action: "Unknown strategy" };
    }
  }

  /**
   * Cleanup expired leases
   */
  cleanupExpiredLeases(): number {
    const now = this.getCurrentTime();
    let cleaned = 0;

    for (const [sessionId, lease] of this.leases.entries()) {
      const expiresAt = new Date(lease.expiresAt).getTime();
      if (now >= expiresAt) {
        this.leases.delete(sessionId);
        this.stopHeartbeat(sessionId);
        cleaned++;
      }
    }

    return cleaned;
  }

  /**
   * Get current time (testable)
   */
  private getCurrentTime(): number {
    return Date.now();
  }

  /**
   * Generate cursor ID
   */
  private generateCursor(sessionId: string, seqNum: number): string {
    return `cursor-${sessionId}-${seqNum}-${Date.now()}`;
  }

  /**
   * Generate lease ID
   */
  private generateLeaseId(): string {
    return `lease-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
  }

  /**
   * Sleep helper
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Shutdown coordinator
   */
  shutdown(): void {
    // Stop all heartbeats
    for (const sessionId of this.heartbeatTimers.keys()) {
      this.stopHeartbeat(sessionId);
    }

    this.leases.clear();
    this.cursors.clear();
  }
}
