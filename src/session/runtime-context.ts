/**
 * M7 production context shaping for PiRuntime. Every model call's context passes through:
 * 1. BlobExternalizer: oversized tool-result text is stored once and replaced by a bounded preview
 *    plus an artifact reference (the persisted session keeps the full text; only the model view
 *    shrinks).
 * 2. ContextBudget: whole leading turns are dropped at user-message boundaries until the estimated
 *    token total fits. The latest user turn and its tool call/result pairs are always kept.
 *    Dropping history happens under a CompactionCoordinator lease per session, so two runs that
 *    share a session never compact it at the same time; without the lease the call keeps the
 *    full (externalized) history instead of racing.
 * 3. SessionTree: one leaf per shaped call records kept/dropped counts; every drop also appends a
 *    compaction entry so the cut point is inspectable.
 */

import { randomUUID } from "node:crypto";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import { BlobExternalizer, InMemoryArtifactStore } from "./blob-externalizer.js";
import { CompactionCoordinator } from "./compaction-coordinator.js";
import { ContextBudget } from "./context-budget.js";
import { SessionTree } from "./session-tree.js";

export interface ContextShapeOptions {
  maxTokens: number;
  marginTokens: number;
  maxInlineBytes: number;
}

export const DEFAULT_CONTEXT_SHAPE: ContextShapeOptions = {
  maxTokens: 24_000,
  marginTokens: 2_000,
  maxInlineBytes: 16 * 1024,
};
const MAX_TREE_ENTRIES = 500;
/** Shared by every shaper in the process: the lease is keyed by session id. */
const compactionLeases = new CompactionCoordinator();

/** Rough, provider-independent estimate (~4 bytes per token) for budget decisions only. */
export function estimateTokens(message: AgentMessage): number {
  return Math.ceil(Buffer.byteLength(JSON.stringify(message) ?? "") / 4);
}

export class RuntimeContextShaper {
  private readonly store = new InMemoryArtifactStore();
  private readonly externalized = new Map<string, string>();
  readonly tree = new SessionTree();
  private root: string | undefined;
  private readonly holder = `shaper-${randomUUID()}`;

  constructor(
    private readonly sessionId: string,
    private readonly options: ContextShapeOptions = DEFAULT_CONTEXT_SHAPE,
  ) {}

  async shape(messages: AgentMessage[]): Promise<AgentMessage[]> {
    const compacted = await Promise.all(messages.map((message) => this.externalize(message)));
    const kept = await this.compact(compacted, this.fitBudget(compacted));
    this.record(messages.length, kept.length);
    return kept;
  }

  private async compact(all: AgentMessage[], kept: AgentMessage[]): Promise<AgentMessage[]> {
    if (kept.length === all.length) return kept;
    const lease = await compactionLeases.acquireLease(this.sessionId, this.holder);
    if (!lease.ok || !lease.value) return all;
    try {
      const dropped = all.length - kept.length;
      if (this.tree.getCurrentSeq() < MAX_TREE_ENTRIES) {
        this.tree.appendCompaction(
          this.sessionId,
          this.rootEntry(),
          dropped,
          lease.value.leaseId,
          { dropped, kept: kept.length },
          [],
          all.slice(0, dropped).reduce((sum, message) => sum + estimateTokens(message), 0),
        );
      }
      return kept;
    } finally {
      await compactionLeases.releaseLease(this.sessionId, this.holder);
    }
  }

  private rootEntry(): string {
    this.root ??= this.tree.appendParent(this.sessionId, null, { title: "model context" }).entryId;
    return this.root;
  }

  private async externalize(message: AgentMessage): Promise<AgentMessage> {
    if ((message as { role?: string }).role !== "toolResult") return message;
    const result = message as Extract<AgentMessage, { role: "toolResult" }>;
    const content = await Promise.all(
      result.content.map(async (part) => {
        if (part.type !== "text" || Buffer.byteLength(part.text) <= this.options.maxInlineBytes) {
          return part;
        }
        const cacheKey = `${result.toolCallId}:${part.text.length}`;
        let replacement = this.externalized.get(cacheKey);
        if (!replacement) {
          const externalizer = new BlobExternalizer(this.store, "session", this.sessionId, {
            maxInlineBytes: this.options.maxInlineBytes,
            maxTruncatedPreviewBytes: 1024,
            maxTotalPayloadBytes: 10 * 1024 * 1024,
          });
          const outcome = await externalizer.processBlob(
            { data: part.text, contentType: "text/plain", metadata: { tool: result.toolName } },
            "tool-result",
          );
          const ref =
            outcome.ok && outcome.blob && !outcome.blob.inline
              ? outcome.blob.artifactRef.id
              : "not-stored";
          replacement =
            `${part.text.slice(0, 1024)}\n[tool result truncated: ${Buffer.byteLength(part.text)} bytes, ` +
            `externalized as ${ref}; ask for a narrower query instead of repeating this call]`;
          this.externalized.set(cacheKey, replacement);
        }
        return { ...part, text: replacement };
      }),
    );
    return { ...result, content } as AgentMessage;
  }

  private fitBudget(messages: AgentMessage[]): AgentMessage[] {
    const budget = new ContextBudget(this.options.maxTokens, this.options.marginTokens);
    budget.allocate("history", this.options.maxTokens - this.options.marginTokens);
    const lastUser = messages.findLastIndex(
      (message) => (message as { role?: string }).role === "user",
    );
    let start = messages.length;
    for (let index = messages.length - 1; index >= 0; index--) {
      const message = messages[index] as AgentMessage;
      if (!budget.consume("history", estimateTokens(message), "context").ok && index < lastUser) {
        break;
      }
      start = index;
    }
    if (start === 0) return messages;
    // Cut only at a user boundary so tool calls and their results are never split.
    const boundary = messages.findIndex(
      (message, index) => index >= start && (message as { role?: string }).role === "user",
    );
    return messages.slice(boundary >= 0 ? Math.min(boundary, lastUser) : Math.max(0, lastUser));
  }

  private record(total: number, kept: number): void {
    if (this.tree.getCurrentSeq() >= MAX_TREE_ENTRIES) return;
    this.tree.appendLeaf(this.sessionId, this.rootEntry(), "assistant_message", {
      total,
      kept,
      dropped: total - kept,
    });
  }
}
