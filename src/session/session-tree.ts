/**
 * Session Tree
 * Append-only session entries with parent/leaf/branch/reset/compaction schema
 * Supports deterministic reconstruction from append-only log
 */

/**
 * Entry type discriminator
 */
export type EntryType =
  | "parent" // Root or parent entry
  | "leaf" // Content entry (user message, assistant message, tool call, tool result)
  | "branch" // Branch point for parallel execution
  | "reset" // Context reset marker
  | "compaction"; // Compaction marker with cursor

/**
 * Base entry structure
 */
export interface BaseEntry {
  entryId: string;
  sessionId: string;
  type: EntryType;
  seqNum: number;
  timestamp: string;
  parentEntryId: string | null;
}

/**
 * Parent entry - root or grouping entry
 */
export interface ParentEntry extends BaseEntry {
  type: "parent";
  title?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Leaf entry - actual content
 */
export interface LeafEntry extends BaseEntry {
  type: "leaf";
  contentType: "user_message" | "assistant_message" | "tool_call" | "tool_result";
  content: unknown;
  tokensUsed?: number;
  metadata?: Record<string, unknown>;
}

/**
 * Branch entry - marks branching point
 */
export interface BranchEntry extends BaseEntry {
  type: "branch";
  branchName: string;
  branchedFrom: string;
  metadata?: Record<string, unknown>;
}

/**
 * Reset entry - marks context reset
 */
export interface ResetEntry extends BaseEntry {
  type: "reset";
  reason: string;
  preservedEntries?: string[];
  metadata?: Record<string, unknown>;
}

/**
 * Compaction entry - marks compaction point
 */
export interface CompactionEntry extends BaseEntry {
  type: "compaction";
  compactedUpTo: number;
  cursor: string;
  compactedContent: unknown;
  originalEntries: string[];
  tokensUsed: number;
  metadata?: Record<string, unknown>;
}

/**
 * Union type for all entries
 */
export type SessionEntry = ParentEntry | LeafEntry | BranchEntry | ResetEntry | CompactionEntry;

/**
 * Session tree builder
 */
export class SessionTree {
  private entries: Map<string, SessionEntry> = new Map();
  private sequenceIndex: Map<number, string> = new Map();
  private nextSeqNum: number = 1;

  /**
   * Append a parent entry
   */
  appendParent(
    sessionId: string,
    parentEntryId: string | null,
    options?: { title?: string; metadata?: Record<string, unknown> },
  ): ParentEntry {
    const entry: ParentEntry = {
      entryId: this.generateEntryId(),
      sessionId,
      type: "parent",
      seqNum: this.nextSeqNum++,
      timestamp: new Date().toISOString(),
      parentEntryId,
      ...options,
    };

    this.entries.set(entry.entryId, entry);
    this.sequenceIndex.set(entry.seqNum, entry.entryId);

    return entry;
  }

  /**
   * Append a leaf entry
   */
  appendLeaf(
    sessionId: string,
    parentEntryId: string,
    contentType: LeafEntry["contentType"],
    content: unknown,
    options?: { tokensUsed?: number; metadata?: Record<string, unknown> },
  ): LeafEntry {
    const entry: LeafEntry = {
      entryId: this.generateEntryId(),
      sessionId,
      type: "leaf",
      seqNum: this.nextSeqNum++,
      timestamp: new Date().toISOString(),
      parentEntryId,
      contentType,
      content,
      ...options,
    };

    this.entries.set(entry.entryId, entry);
    this.sequenceIndex.set(entry.seqNum, entry.entryId);

    return entry;
  }

  /**
   * Append a branch entry
   */
  appendBranch(
    sessionId: string,
    parentEntryId: string,
    branchName: string,
    branchedFrom: string,
    options?: { metadata?: Record<string, unknown> },
  ): BranchEntry {
    const entry: BranchEntry = {
      entryId: this.generateEntryId(),
      sessionId,
      type: "branch",
      seqNum: this.nextSeqNum++,
      timestamp: new Date().toISOString(),
      parentEntryId,
      branchName,
      branchedFrom,
      ...options,
    };

    this.entries.set(entry.entryId, entry);
    this.sequenceIndex.set(entry.seqNum, entry.entryId);

    return entry;
  }

  /**
   * Append a reset entry
   */
  appendReset(
    sessionId: string,
    parentEntryId: string | null,
    reason: string,
    options?: { preservedEntries?: string[]; metadata?: Record<string, unknown> },
  ): ResetEntry {
    const entry: ResetEntry = {
      entryId: this.generateEntryId(),
      sessionId,
      type: "reset",
      seqNum: this.nextSeqNum++,
      timestamp: new Date().toISOString(),
      parentEntryId,
      reason,
      ...options,
    };

    this.entries.set(entry.entryId, entry);
    this.sequenceIndex.set(entry.seqNum, entry.entryId);

    return entry;
  }

  /**
   * Append a compaction entry
   */
  appendCompaction(
    sessionId: string,
    parentEntryId: string | null,
    compactedUpTo: number,
    cursor: string,
    compactedContent: unknown,
    originalEntries: string[],
    tokensUsed: number,
    options?: { metadata?: Record<string, unknown> },
  ): CompactionEntry {
    const entry: CompactionEntry = {
      entryId: this.generateEntryId(),
      sessionId,
      type: "compaction",
      seqNum: this.nextSeqNum++,
      timestamp: new Date().toISOString(),
      parentEntryId,
      compactedUpTo,
      cursor,
      compactedContent,
      originalEntries,
      tokensUsed,
      ...options,
    };

    this.entries.set(entry.entryId, entry);
    this.sequenceIndex.set(entry.seqNum, entry.entryId);

    return entry;
  }

  /**
   * Get entry by ID
   */
  getEntry(entryId: string): SessionEntry | undefined {
    return this.entries.get(entryId);
  }

  /**
   * Get entry by sequence number
   */
  getEntryBySeq(seqNum: number): SessionEntry | undefined {
    const entryId = this.sequenceIndex.get(seqNum);
    return entryId ? this.entries.get(entryId) : undefined;
  }

  /**
   * Get all entries in sequence order
   */
  getAllEntries(): SessionEntry[] {
    const entries: SessionEntry[] = [];
    for (let i = 1; i < this.nextSeqNum; i++) {
      const entry = this.getEntryBySeq(i);
      if (entry) {
        entries.push(entry);
      }
    }
    return entries;
  }

  /**
   * Get entries for a session
   */
  getSessionEntries(sessionId: string): SessionEntry[] {
    return this.getAllEntries().filter((e) => e.sessionId === sessionId);
  }

  /**
   * Get children of an entry
   */
  getChildren(parentEntryId: string): SessionEntry[] {
    return this.getAllEntries().filter((e) => e.parentEntryId === parentEntryId);
  }

  /**
   * Get parent chain for an entry
   */
  getParentChain(entryId: string): SessionEntry[] {
    const chain: SessionEntry[] = [];
    let current = this.entries.get(entryId);

    while (current) {
      chain.unshift(current);
      if (!current.parentEntryId) {
        break;
      }
      current = this.entries.get(current.parentEntryId);
    }

    return chain;
  }

  /**
   * Reconstruct session from entries
   */
  reconstructSession(sessionId: string): {
    entries: SessionEntry[];
    branches: Map<string, SessionEntry[]>;
    compactions: CompactionEntry[];
    resets: ResetEntry[];
  } {
    const sessionEntries = this.getSessionEntries(sessionId);

    const branches = new Map<string, SessionEntry[]>();
    const compactions: CompactionEntry[] = [];
    const resets: ResetEntry[] = [];

    for (const entry of sessionEntries) {
      if (entry.type === "branch") {
        const branchEntries = this.getBranchEntries(entry.entryId);
        branches.set(entry.branchName, branchEntries);
      } else if (entry.type === "compaction") {
        compactions.push(entry);
      } else if (entry.type === "reset") {
        resets.push(entry);
      }
    }

    return {
      entries: sessionEntries,
      branches,
      compactions,
      resets,
    };
  }

  /**
   * Get all entries in a branch
   */
  private getBranchEntries(branchEntryId: string): SessionEntry[] {
    const entries: SessionEntry[] = [];
    const children = this.getChildren(branchEntryId);

    for (const child of children) {
      entries.push(child);
      if (child.type === "parent" || child.type === "branch") {
        entries.push(...this.getBranchEntries(child.entryId));
      }
    }

    return entries;
  }

  /**
   * Get entries since sequence number
   */
  getEntriesSince(seqNum: number): SessionEntry[] {
    const entries: SessionEntry[] = [];
    for (let i = seqNum + 1; i < this.nextSeqNum; i++) {
      const entry = this.getEntryBySeq(i);
      if (entry) {
        entries.push(entry);
      }
    }
    return entries;
  }

  /**
   * Get entries up to sequence number
   */
  getEntriesUpTo(seqNum: number): SessionEntry[] {
    const entries: SessionEntry[] = [];
    for (let i = 1; i <= seqNum; i++) {
      const entry = this.getEntryBySeq(i);
      if (entry) {
        entries.push(entry);
      }
    }
    return entries;
  }

  /**
   * Get last compaction for session
   */
  getLastCompaction(sessionId: string): CompactionEntry | undefined {
    const compactions = this.getSessionEntries(sessionId)
      .filter((e): e is CompactionEntry => e.type === "compaction")
      .sort((a, b) => b.seqNum - a.seqNum);

    return compactions[0];
  }

  /**
   * Verify contiguous sequence
   */
  verifyContiguous(): { ok: boolean; gaps: number[] } {
    const gaps: number[] = [];

    for (let i = 1; i < this.nextSeqNum; i++) {
      if (!this.sequenceIndex.has(i)) {
        gaps.push(i);
      }
    }

    return {
      ok: gaps.length === 0,
      gaps,
    };
  }

  /**
   * Get current sequence number
   */
  getCurrentSeq(): number {
    return this.nextSeqNum - 1;
  }

  /**
   * Serialize to append-only log
   */
  serialize(): string[] {
    const lines: string[] = [];
    for (let i = 1; i < this.nextSeqNum; i++) {
      const entry = this.getEntryBySeq(i);
      if (entry) {
        lines.push(JSON.stringify(entry));
      }
    }
    return lines;
  }

  /**
   * Deserialize from append-only log
   */
  static deserialize(lines: string[]): SessionTree {
    const tree = new SessionTree();

    for (const line of lines) {
      const entry = JSON.parse(line) as SessionEntry;
      tree.entries.set(entry.entryId, entry);
      tree.sequenceIndex.set(entry.seqNum, entry.entryId);
      tree.nextSeqNum = Math.max(tree.nextSeqNum, entry.seqNum + 1);
    }

    return tree;
  }

  /**
   * Generate entry ID
   */
  private generateEntryId(): string {
    return `entry-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  }
}
