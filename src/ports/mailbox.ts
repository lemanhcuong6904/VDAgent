/**
 * Mailbox Port
 * Inter-agent communication with question/result/wake, handoff CAS, bounce/dedup, cycle detection
 */

import type { AgentScope } from "../contracts/index.js";

/**
 * Message envelope
 */
export interface Message<T = unknown> {
  messageId: string;
  fromAgentId: string;
  toAgentId: string;
  scope: AgentScope;
  content: T;
  correlationId?: string;
  replyTo?: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

/**
 * Question message - agent asking for something
 */
export interface Question<TInput = unknown> {
  type: "question";
  questionId: string;
  input: TInput;
  timeoutMs?: number;
  priority?: "low" | "normal" | "high";
}

/**
 * Result message - response to question
 */
export interface Result<TOutput = unknown> {
  type: "result";
  questionId: string;
  status: "success" | "error" | "timeout";
  output?: TOutput;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
}

/**
 * Wake notification
 */
export interface Wake {
  type: "wake";
  reason: string;
  data?: unknown;
}

/**
 * Handoff work item
 */
export interface HandoffItem<T = unknown> {
  itemId: string;
  workType: string;
  payload: T;
  version: number;
  ownerId: string | null;
  status: "available" | "claimed" | "completed";
  createdAt: string;
  claimedAt?: string;
  completedAt?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Wait-for dependency
 */
export interface WaitForEdge {
  waitingAgentId: string;
  blockedOnAgentId: string;
  questionId: string;
  since: string;
}

/**
 * Mailbox port for inter-agent communication
 */
export interface MailboxPort {
  /**
   * Send a question to another agent
   */
  ask<TInput = unknown, _TOutput = unknown>(
    message: Message<Question<TInput>>,
  ): Promise<{ messageId: string; questionId: string }>;

  /**
   * Post a result to a question
   */
  answer<TOutput = unknown>(message: Message<Result<TOutput>>): Promise<{ delivered: boolean }>;

  /**
   * Wake an agent with notification
   */
  wake(message: Message<Wake>): Promise<{ delivered: boolean }>;

  /**
   * Receive messages for an agent
   */
  receive(agentId: string, maxCount?: number): Promise<Message[]>;

  /**
   * Wait for result to a specific question
   */
  waitForResult(
    agentId: string,
    questionId: string,
    timeoutMs?: number,
  ): Promise<Message<Result> | null>;

  /**
   * Handoff: try to claim work item (CAS)
   */
  claimWork<T = unknown>(
    itemId: string,
    claimerId: string,
    expectedVersion: number,
  ): Promise<{ success: boolean; item?: HandoffItem<T> }>;

  /**
   * Handoff: complete work item
   */
  completeWork(itemId: string, completerId: string): Promise<{ success: boolean }>;

  /**
   * Handoff: release work item back to available
   */
  releaseWork(itemId: string, releaserId: string): Promise<{ success: boolean }>;

  /**
   * Add work item to handoff pool
   */
  addWorkItem<T = unknown>(item: HandoffItem<T>): Promise<{ itemId: string }>;

  /**
   * Get available work items
   */
  getAvailableWork(workType?: string): Promise<HandoffItem[]>;

  /**
   * Check if message was already processed (dedup)
   */
  isDuplicate(messageId: string): Promise<boolean>;

  /**
   * Mark message as processed (dedup)
   */
  markProcessed(messageId: string): Promise<void>;

  /**
   * Check if adding wait-for edge would create cycle
   */
  wouldCreateCycle(waitingAgentId: string, blockedOnAgentId: string): Promise<boolean>;

  /**
   * Add wait-for dependency edge
   */
  addWaitFor(edge: WaitForEdge): Promise<{ added: boolean; reason?: string }>;

  /**
   * Remove wait-for dependency edge
   */
  removeWaitFor(questionId: string): Promise<void>;

  /**
   * Get all wait-for edges
   */
  getWaitForGraph(): Promise<WaitForEdge[]>;
}

/**
 * In-memory implementation of MailboxPort
 */
export class InMemoryMailbox implements MailboxPort {
  private mailboxes: Map<string, Message[]> = new Map();
  private processedMessages: Set<string> = new Set();
  private workItems: Map<string, HandoffItem> = new Map();
  private waitForGraph: Map<string, WaitForEdge> = new Map();
  private resultNotifications: Map<string, Array<(result: Message<Result>) => void>> = new Map();

  async ask<TInput = unknown, _TOutput = unknown>(
    message: Message<Question<TInput>>,
  ): Promise<{ messageId: string; questionId: string }> {
    // Check for duplicate
    if (this.processedMessages.has(message.messageId)) {
      throw new Error(`Message ${message.messageId} already processed (duplicate)`);
    }

    // Check for wait-for cycle
    const question = message.content;
    const wouldCycle = await this.wouldCreateCycle(message.fromAgentId, message.toAgentId);

    if (wouldCycle) {
      throw new Error(
        `Cannot ask: would create wait-for cycle between ${message.fromAgentId} and ${message.toAgentId}`,
      );
    }

    // Add wait-for edge
    const edge: WaitForEdge = {
      waitingAgentId: message.fromAgentId,
      blockedOnAgentId: message.toAgentId,
      questionId: question.questionId,
      since: new Date().toISOString(),
    };
    this.waitForGraph.set(question.questionId, edge);

    // Deliver message
    const mailbox = this.mailboxes.get(message.toAgentId) || [];
    mailbox.push(message);
    this.mailboxes.set(message.toAgentId, mailbox);

    // Mark as processed
    this.processedMessages.add(message.messageId);

    return {
      messageId: message.messageId,
      questionId: question.questionId,
    };
  }

  async answer<TOutput = unknown>(
    message: Message<Result<TOutput>>,
  ): Promise<{ delivered: boolean }> {
    // Check for duplicate
    if (this.processedMessages.has(message.messageId)) {
      return { delivered: false }; // Bounce duplicate
    }

    const result = message.content;

    // Remove wait-for edge
    this.waitForGraph.delete(result.questionId);

    // Deliver message
    const mailbox = this.mailboxes.get(message.toAgentId) || [];
    mailbox.push(message);
    this.mailboxes.set(message.toAgentId, mailbox);

    // Mark as processed
    this.processedMessages.add(message.messageId);

    // Notify waiters
    const waiters = this.resultNotifications.get(result.questionId) || [];
    for (const notify of waiters) {
      notify(message as Message<Result>);
    }
    this.resultNotifications.delete(result.questionId);

    return { delivered: true };
  }

  async wake(message: Message<Wake>): Promise<{ delivered: boolean }> {
    // Check for duplicate
    if (this.processedMessages.has(message.messageId)) {
      return { delivered: false }; // Bounce duplicate
    }

    // Deliver message
    const mailbox = this.mailboxes.get(message.toAgentId) || [];
    mailbox.push(message);
    this.mailboxes.set(message.toAgentId, mailbox);

    // Mark as processed
    this.processedMessages.add(message.messageId);

    return { delivered: true };
  }

  async receive(agentId: string, maxCount?: number): Promise<Message[]> {
    const mailbox = this.mailboxes.get(agentId) || [];
    const count = maxCount || mailbox.length;
    const messages = mailbox.splice(0, count);
    this.mailboxes.set(agentId, mailbox);
    return messages;
  }

  async waitForResult(
    agentId: string,
    questionId: string,
    timeoutMs?: number,
  ): Promise<Message<Result> | null> {
    // Check if result already in mailbox
    const mailbox = this.mailboxes.get(agentId) || [];
    const existing = mailbox.find(
      (msg) =>
        typeof msg.content === "object" &&
        msg.content !== null &&
        "type" in msg.content &&
        msg.content.type === "result" &&
        (msg.content as Result).questionId === questionId,
    );

    if (existing) {
      return existing as Message<Result>;
    }

    // Wait for result notification
    return new Promise((resolve) => {
      const timeout = timeoutMs || 60000;
      const timer = setTimeout(() => {
        // Remove waiter
        const waiters = this.resultNotifications.get(questionId) || [];
        const index = waiters.indexOf(notify);
        if (index >= 0) {
          waiters.splice(index, 1);
        }
        resolve(null);
      }, timeout);

      const notify = (result: Message<Result>) => {
        clearTimeout(timer);
        resolve(result);
      };

      const waiters = this.resultNotifications.get(questionId) || [];
      waiters.push(notify);
      this.resultNotifications.set(questionId, waiters);
    });
  }

  async claimWork<T = unknown>(
    itemId: string,
    claimerId: string,
    expectedVersion: number,
  ): Promise<{ success: boolean; item?: HandoffItem<T> }> {
    const item = this.workItems.get(itemId);

    if (!item) {
      return { success: false };
    }

    // CAS check: version must match and status must be available
    if (item.version !== expectedVersion || item.status !== "available") {
      return { success: false };
    }

    // Claim item
    const claimed: HandoffItem<T> = {
      ...item,
      version: item.version + 1,
      ownerId: claimerId,
      status: "claimed",
      claimedAt: new Date().toISOString(),
    } as HandoffItem<T>;

    this.workItems.set(itemId, claimed);

    return { success: true, item: claimed };
  }

  async completeWork(itemId: string, completerId: string): Promise<{ success: boolean }> {
    const item = this.workItems.get(itemId);

    if (!item) {
      return { success: false };
    }

    // Must be claimed by the completer
    if (item.status !== "claimed" || item.ownerId !== completerId) {
      return { success: false };
    }

    // Mark completed
    const completed: HandoffItem = {
      ...item,
      status: "completed",
      completedAt: new Date().toISOString(),
    };

    this.workItems.set(itemId, completed);

    return { success: true };
  }

  async releaseWork(itemId: string, releaserId: string): Promise<{ success: boolean }> {
    const item = this.workItems.get(itemId);

    if (!item) {
      return { success: false };
    }

    // Must be claimed by the releaser
    if (item.status !== "claimed" || item.ownerId !== releaserId) {
      return { success: false };
    }

    // Release back to available
    const released: HandoffItem = {
      ...item,
      version: item.version + 1,
      ownerId: null,
      status: "available",
      claimedAt: undefined,
    };

    this.workItems.set(itemId, released);

    return { success: true };
  }

  async addWorkItem<T = unknown>(item: HandoffItem<T>): Promise<{ itemId: string }> {
    this.workItems.set(item.itemId, item as HandoffItem);
    return { itemId: item.itemId };
  }

  async getAvailableWork(workType?: string): Promise<HandoffItem[]> {
    const items = Array.from(this.workItems.values()).filter((item) => item.status === "available");

    if (workType) {
      return items.filter((item) => item.workType === workType);
    }

    return items;
  }

  async isDuplicate(messageId: string): Promise<boolean> {
    return this.processedMessages.has(messageId);
  }

  async markProcessed(messageId: string): Promise<void> {
    this.processedMessages.add(messageId);
  }

  async wouldCreateCycle(waitingAgentId: string, blockedOnAgentId: string): Promise<boolean> {
    // Build adjacency list from wait-for graph
    const graph = new Map<string, Set<string>>();

    for (const edge of this.waitForGraph.values()) {
      const neighbors = graph.get(edge.waitingAgentId) || new Set();
      neighbors.add(edge.blockedOnAgentId);
      graph.set(edge.waitingAgentId, neighbors);
    }

    // Add proposed edge
    const neighbors = graph.get(waitingAgentId) || new Set();
    neighbors.add(blockedOnAgentId);
    graph.set(waitingAgentId, neighbors);

    // DFS cycle detection from waitingAgentId
    const visited = new Set<string>();
    const recStack = new Set<string>();

    const hasCycle = (node: string): boolean => {
      visited.add(node);
      recStack.add(node);

      const neighbors = graph.get(node);
      if (neighbors) {
        for (const neighbor of neighbors) {
          if (!visited.has(neighbor)) {
            if (hasCycle(neighbor)) {
              return true;
            }
          } else if (recStack.has(neighbor)) {
            return true; // Back edge = cycle
          }
        }
      }

      recStack.delete(node);
      return false;
    };

    return hasCycle(waitingAgentId);
  }

  async addWaitFor(edge: WaitForEdge): Promise<{ added: boolean; reason?: string }> {
    // Check for cycle
    const wouldCycle = await this.wouldCreateCycle(edge.waitingAgentId, edge.blockedOnAgentId);

    if (wouldCycle) {
      return {
        added: false,
        reason: `Would create wait-for cycle: ${edge.waitingAgentId} -> ${edge.blockedOnAgentId}`,
      };
    }

    this.waitForGraph.set(edge.questionId, edge);
    return { added: true };
  }

  async removeWaitFor(questionId: string): Promise<void> {
    this.waitForGraph.delete(questionId);
  }

  async getWaitForGraph(): Promise<WaitForEdge[]> {
    return Array.from(this.waitForGraph.values());
  }
}
