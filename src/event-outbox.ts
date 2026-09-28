/**
 * Event Outbox
 * Transactional outbox pattern for reliable event emission
 */

import type { AgentScope } from "./contracts/index.js";

/**
 * Domain event
 */
export interface DomainEvent {
  eventId: string;
  eventType: string;
  aggregateId: string;
  aggregateType: string;
  payload: unknown;
  scope: AgentScope;
  timestamp: string;
  causationId?: string;
  correlationId?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Outbox entry
 */
export interface OutboxEntry {
  entryId: string;
  event: DomainEvent;
  status: "pending" | "processing" | "published" | "failed";
  attempts: number;
  maxAttempts: number;
  nextRetryAt?: string;
  publishedAt?: string;
  error?: {
    code: string;
    message: string;
    lastAttemptAt: string;
  };
  createdAt: string;
  updatedAt: string;
}

/**
 * Event consumer
 */
export interface EventConsumer {
  consumerId: string;
  eventTypes: string[];
  handler: (event: DomainEvent) => Promise<void>;
}

/**
 * Consumer checkpoint
 */
export interface ConsumerCheckpoint {
  consumerId: string;
  lastProcessedEventId: string;
  lastProcessedAt: string;
  processedCount: number;
}

/**
 * Dead letter entry
 */
export interface DeadLetterEntry {
  entryId: string;
  event: DomainEvent;
  consumerId: string;
  error: {
    code: string;
    message: string;
    stack?: string;
  };
  attempts: number;
  failedAt: string;
  canRetry: boolean;
}

/**
 * Transactional event outbox for reliable event emission
 */
export class EventOutbox {
  private outbox: Map<string, OutboxEntry> = new Map();
  private consumers: Map<string, EventConsumer> = new Map();
  private checkpoints: Map<string, ConsumerCheckpoint> = new Map();
  private deadLetters: Map<string, DeadLetterEntry> = new Map();
  private processedEvents: Set<string> = new Set();
  private publishInterval?: NodeJS.Timeout;

  private readonly maxAttempts: number;
  private readonly retryDelayMs: number;
  private readonly publishIntervalMs: number;

  constructor(config?: {
    maxAttempts?: number;
    retryDelayMs?: number;
    publishIntervalMs?: number;
  }) {
    this.maxAttempts = config?.maxAttempts || 3;
    this.retryDelayMs = config?.retryDelayMs || 5000;
    this.publishIntervalMs = config?.publishIntervalMs || 1000;
  }

  /**
   * Start the outbox publisher
   */
  start(): void {
    if (this.publishInterval) {
      return;
    }

    this.publishInterval = setInterval(() => {
      this.publishPendingEvents().catch((err) => {
        console.error("Error publishing events:", err);
      });
    }, this.publishIntervalMs);
  }

  /**
   * Stop the outbox publisher
   */
  stop(): void {
    if (this.publishInterval) {
      clearInterval(this.publishInterval);
      this.publishInterval = undefined;
    }
  }

  /**
   * Append event to outbox (transactional)
   */
  async append(event: DomainEvent): Promise<OutboxEntry> {
    const entry: OutboxEntry = {
      entryId: `outbox-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      event,
      status: "pending",
      attempts: 0,
      maxAttempts: this.maxAttempts,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    this.outbox.set(entry.entryId, entry);
    return entry;
  }

  /**
   * Deliver one already-durable event (e.g. claimed from platform_outbox_events) to consumers with
   * per-consumer dedupe, checkpoints and dead letters. Throws if any consumer failed, so the durable
   * publisher keeps the row for retry; consumers that already succeeded are skipped on redelivery.
   */
  async deliver(event: DomainEvent): Promise<void> {
    await this.deliverToConsumers(event);
  }

  /**
   * Publish pending events to consumers
   */
  private async publishPendingEvents(): Promise<void> {
    const now = new Date();
    const pending = Array.from(this.outbox.values()).filter(
      (entry) =>
        (entry.status === "pending" ||
          (entry.status === "failed" && entry.nextRetryAt && new Date(entry.nextRetryAt) <= now)) &&
        entry.attempts < entry.maxAttempts,
    );

    for (const entry of pending) {
      await this.publishEntry(entry);
    }
  }

  /**
   * Publish a single outbox entry
   */
  private async publishEntry(entry: OutboxEntry): Promise<void> {
    entry.status = "processing";
    entry.attempts++;
    entry.updatedAt = new Date().toISOString();

    try {
      await this.deliverToConsumers(entry.event);

      entry.status = "published";
      entry.publishedAt = new Date().toISOString();
      entry.updatedAt = entry.publishedAt;
    } catch (error) {
      entry.status = "failed";
      entry.error = {
        code: "publish_error",
        message: error instanceof Error ? error.message : "Unknown error",
        lastAttemptAt: new Date().toISOString(),
      };

      if (entry.attempts < entry.maxAttempts) {
        // Schedule retry
        const delay = this.retryDelayMs * 2 ** (entry.attempts - 1);
        entry.nextRetryAt = new Date(Date.now() + delay).toISOString();
      }

      entry.updatedAt = new Date().toISOString();
    }
  }

  /**
   * Deliver event to all matching consumers
   */
  private async deliverToConsumers(event: DomainEvent): Promise<void> {
    const matchingConsumers = Array.from(this.consumers.values()).filter(
      (consumer) =>
        consumer.eventTypes.includes("*") || consumer.eventTypes.includes(event.eventType),
    );

    for (const consumer of matchingConsumers) {
      await this.deliverToConsumer(consumer, event);
    }
  }

  /**
   * Deliver event to a specific consumer with idempotency
   */
  private async deliverToConsumer(consumer: EventConsumer, event: DomainEvent): Promise<void> {
    // Check idempotency
    const processedKey = `${consumer.consumerId}:${event.eventId}`;
    if (this.processedEvents.has(processedKey)) {
      return; // Already processed
    }

    try {
      await consumer.handler(event);

      // Mark as processed
      this.processedEvents.add(processedKey);

      // Update checkpoint
      this.updateCheckpoint(consumer.consumerId, event.eventId);
    } catch (error) {
      // Send to dead letter queue
      await this.sendToDeadLetter(consumer, event, error);
      throw error;
    }
  }

  /**
   * Update consumer checkpoint
   */
  private updateCheckpoint(consumerId: string, eventId: string): void {
    const checkpoint = this.checkpoints.get(consumerId) || {
      consumerId,
      lastProcessedEventId: "",
      lastProcessedAt: "",
      processedCount: 0,
    };

    checkpoint.lastProcessedEventId = eventId;
    checkpoint.lastProcessedAt = new Date().toISOString();
    checkpoint.processedCount++;

    this.checkpoints.set(consumerId, checkpoint);
  }

  /**
   * Send failed event to dead letter queue
   */
  private async sendToDeadLetter(
    consumer: EventConsumer,
    event: DomainEvent,
    error: unknown,
  ): Promise<void> {
    // Check if dead letter already exists for this consumer+event
    const existing = Array.from(this.deadLetters.values()).find(
      (dl) => dl.consumerId === consumer.consumerId && dl.event.eventId === event.eventId,
    );

    if (existing) {
      // Update existing dead letter
      existing.attempts++;
      existing.failedAt = new Date().toISOString();
      existing.error = {
        code: "consumer_error",
        message: error instanceof Error ? error.message : "Unknown error",
        stack: error instanceof Error ? error.stack : undefined,
      };

      if (existing.attempts > this.maxAttempts) {
        existing.canRetry = false;
      }
    } else {
      // Create new dead letter
      const deadLetter: DeadLetterEntry = {
        entryId: `dead-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        event,
        consumerId: consumer.consumerId,
        error: {
          code: "consumer_error",
          message: error instanceof Error ? error.message : "Unknown error",
          stack: error instanceof Error ? error.stack : undefined,
        },
        attempts: 1,
        failedAt: new Date().toISOString(),
        canRetry: true,
      };

      this.deadLetters.set(deadLetter.entryId, deadLetter);
    }
  }

  /**
   * Register an event consumer
   */
  registerConsumer(consumer: EventConsumer): void {
    this.consumers.set(consumer.consumerId, consumer);
  }

  /**
   * Unregister an event consumer
   */
  unregisterConsumer(consumerId: string): void {
    this.consumers.delete(consumerId);
  }

  /**
   * Get outbox entries by status
   */
  getEntriesByStatus(status: OutboxEntry["status"]): OutboxEntry[] {
    return Array.from(this.outbox.values()).filter((entry) => entry.status === status);
  }

  /**
   * Get consumer checkpoint
   */
  getCheckpoint(consumerId: string): ConsumerCheckpoint | undefined {
    return this.checkpoints.get(consumerId);
  }

  /**
   * Get dead letter entries
   */
  getDeadLetters(consumerId?: string): DeadLetterEntry[] {
    const entries = Array.from(this.deadLetters.values());
    if (consumerId) {
      return entries.filter((entry) => entry.consumerId === consumerId);
    }
    return entries;
  }

  /**
   * Retry dead letter entry
   */
  async retryDeadLetter(entryId: string): Promise<boolean> {
    const deadLetter = this.deadLetters.get(entryId);
    if (!deadLetter?.canRetry) {
      return false;
    }

    const consumer = this.consumers.get(deadLetter.consumerId);
    if (!consumer) {
      return false;
    }

    // Clear idempotency to allow retry
    const processedKey = `${deadLetter.consumerId}:${deadLetter.event.eventId}`;
    this.processedEvents.delete(processedKey);

    try {
      await this.deliverToConsumer(consumer, deadLetter.event);
      this.deadLetters.delete(entryId);
      return true;
    } catch (_error) {
      deadLetter.attempts++;
      deadLetter.failedAt = new Date().toISOString();

      if (deadLetter.attempts > this.maxAttempts) {
        deadLetter.canRetry = false;
      }

      return false;
    }
  }

  /**
   * Replay events from a checkpoint
   */
  async replay(consumerId: string, fromEventId: string, toEventId?: string): Promise<number> {
    const consumer = this.consumers.get(consumerId);
    if (!consumer) {
      throw new Error(`Consumer ${consumerId} not found`);
    }

    // Get all published events
    const publishedEntries = Array.from(this.outbox.values())
      .filter((entry) => entry.status === "published")
      .sort((a, b) => a.event.timestamp.localeCompare(b.event.timestamp));

    // Find range
    const startIdx = publishedEntries.findIndex((entry) => entry.event.eventId === fromEventId);

    if (startIdx === -1) {
      throw new Error(`Event ${fromEventId} not found`);
    }

    let endIdx = publishedEntries.length;
    if (toEventId) {
      const toIdx = publishedEntries.findIndex((entry) => entry.event.eventId === toEventId);
      if (toIdx !== -1) {
        endIdx = toIdx + 1;
      }
    }

    // Clear processed events for this consumer to allow reprocessing
    const processedKeys = Array.from(this.processedEvents).filter((key) =>
      key.startsWith(`${consumerId}:`),
    );
    for (const key of processedKeys) {
      this.processedEvents.delete(key);
    }

    // Replay events
    let replayed = 0;
    for (let i = startIdx; i < endIdx; i++) {
      const entry = publishedEntries[i];
      try {
        await this.deliverToConsumer(consumer, entry.event);
        replayed++;
      } catch (error) {
        // Continue with next event
        console.error(`Failed to replay event ${entry.event.eventId}:`, error);
      }
    }

    return replayed;
  }

  /**
   * Reconcile consumer state
   */
  async reconcile(consumerId: string): Promise<{
    processed: number;
    skipped: number;
    failed: number;
  }> {
    const consumer = this.consumers.get(consumerId);
    if (!consumer) {
      throw new Error(`Consumer ${consumerId} not found`);
    }

    const _checkpoint = this.checkpoints.get(consumerId);

    const publishedEntries = Array.from(this.outbox.values())
      .filter((entry) => entry.status === "published")
      .sort((a, b) => a.event.timestamp.localeCompare(b.event.timestamp));

    let processed = 0;
    let skipped = 0;
    let failed = 0;

    for (const entry of publishedEntries) {
      const processedKey = `${consumerId}:${entry.event.eventId}`;

      if (this.processedEvents.has(processedKey)) {
        skipped++;
        continue;
      }

      // Process all events that match the consumer's types
      if (
        !consumer.eventTypes.includes("*") &&
        !consumer.eventTypes.includes(entry.event.eventType)
      ) {
        continue;
      }

      try {
        await this.deliverToConsumer(consumer, entry.event);
        processed++;
      } catch (_error) {
        failed++;
      }
    }

    return { processed, skipped, failed };
  }

  /**
   * Get statistics
   */
  getStatistics(): {
    outbox: {
      total: number;
      pending: number;
      processing: number;
      published: number;
      failed: number;
    };
    consumers: number;
    deadLetters: number;
    processedEvents: number;
  } {
    const entries = Array.from(this.outbox.values());
    return {
      outbox: {
        total: entries.length,
        pending: entries.filter((e) => e.status === "pending").length,
        processing: entries.filter((e) => e.status === "processing").length,
        published: entries.filter((e) => e.status === "published").length,
        failed: entries.filter((e) => e.status === "failed").length,
      },
      consumers: this.consumers.size,
      deadLetters: this.deadLetters.size,
      processedEvents: this.processedEvents.size,
    };
  }
}
