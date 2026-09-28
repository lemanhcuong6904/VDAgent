import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DomainEvent, EventConsumer } from "../src/event-outbox.js";
import { EventOutbox } from "../src/event-outbox.js";
import { testScope } from "./helpers/scope.js";

describe("EventOutbox", () => {
  let outbox: EventOutbox;

  const sampleScope = testScope();

  beforeEach(() => {
    outbox = new EventOutbox({
      maxAttempts: 3,
      retryDelayMs: 100,
      publishIntervalMs: 50,
    });
  });

  afterEach(() => {
    outbox.stop();
  });

  describe("append", () => {
    it("should append event to outbox", async () => {
      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: { input: "test" },
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      const entry = await outbox.append(event);

      expect(entry.event).toEqual(event);
      expect(entry.status).toBe("pending");
      expect(entry.attempts).toBe(0);
    });

    it("should assign unique entry IDs", async () => {
      const event1: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      const event2: DomainEvent = {
        eventId: "evt-2",
        eventType: "run.completed",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      const entry1 = await outbox.append(event1);
      const entry2 = await outbox.append(event2);

      expect(entry1.entryId).not.toBe(entry2.entryId);
    });
  });

  describe("consumer registration", () => {
    it("should register consumer", () => {
      const handler = vi.fn();
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const stats = outbox.getStatistics();
      expect(stats.consumers).toBe(1);
    });

    it("should unregister consumer", () => {
      const handler = vi.fn();
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);
      outbox.unregisterConsumer("consumer-1");

      const stats = outbox.getStatistics();
      expect(stats.consumers).toBe(0);
    });
  });

  describe("event publishing", () => {
    it("should publish events to matching consumers", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: { input: "test" },
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 150));

      expect(handler).toHaveBeenCalledWith(event);

      const entries = outbox.getEntriesByStatus("published");
      expect(entries).toHaveLength(1);
    });

    it("should publish to wildcard consumers", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["*"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event1: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      const event2: DomainEvent = {
        eventId: "evt-2",
        eventType: "run.completed",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event1);
      await outbox.append(event2);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 150));

      expect(handler).toHaveBeenCalledTimes(2);
    });

    it("should not publish to non-matching consumers", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.completed"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 150));

      expect(handler).not.toHaveBeenCalled();
    });

    it("should handle multiple consumers", async () => {
      const handler1 = vi.fn().mockResolvedValue(undefined);
      const handler2 = vi.fn().mockResolvedValue(undefined);

      const consumer1: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler: handler1,
      };

      const consumer2: EventConsumer = {
        consumerId: "consumer-2",
        eventTypes: ["run.started"],
        handler: handler2,
      };

      outbox.registerConsumer(consumer1);
      outbox.registerConsumer(consumer2);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 150));

      expect(handler1).toHaveBeenCalledWith(event);
      expect(handler2).toHaveBeenCalledWith(event);
    });
  });

  describe("idempotency", () => {
    it("should not deliver same event twice to same consumer", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 150));

      expect(handler).toHaveBeenCalledTimes(1);

      const stats = outbox.getStatistics();
      expect(stats.processedEvents).toBe(1);
    });

    it("should update checkpoint after successful delivery", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 150));

      const checkpoint = outbox.getCheckpoint("consumer-1");
      expect(checkpoint?.lastProcessedEventId).toBe("evt-1");
      expect(checkpoint?.processedCount).toBe(1);
    });
  });

  describe("retry and failure handling", () => {
    it("should retry failed events", async () => {
      let attempts = 0;
      const handler = vi.fn().mockImplementation(async () => {
        attempts++;
        if (attempts < 2) {
          throw new Error("Transient error");
        }
      });

      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 400));

      expect(handler).toHaveBeenCalledTimes(2);

      const entries = outbox.getEntriesByStatus("published");
      expect(entries).toHaveLength(1);
    });

    it("should send to dead letter queue after max attempts", async () => {
      const handler = vi.fn().mockRejectedValue(new Error("Permanent error"));

      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 600));

      const deadLetters = outbox.getDeadLetters();
      expect(deadLetters).toHaveLength(1);
      expect(deadLetters[0].event.eventId).toBe("evt-1");
      expect(deadLetters[0].consumerId).toBe("consumer-1");

      const stats = outbox.getStatistics();
      expect(stats.deadLetters).toBe(1);
    });

    it("should track failed outbox entries", async () => {
      const handler = vi.fn().mockRejectedValue(new Error("Error"));

      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 600));

      const failed = outbox.getEntriesByStatus("failed");
      expect(failed.length).toBeGreaterThan(0);
      expect(failed[0].attempts).toBe(3);
    });
  });

  describe("replay", () => {
    it("should replay events from checkpoint", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["*"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event1: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:00:00Z").toISOString(),
      };

      const event2: DomainEvent = {
        eventId: "evt-2",
        eventType: "run.completed",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:01:00Z").toISOString(),
      };

      const event3: DomainEvent = {
        eventId: "evt-3",
        eventType: "run.started",
        aggregateId: "run-2",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:02:00Z").toISOString(),
      };

      await outbox.append(event1);
      await outbox.append(event2);
      await outbox.append(event3);

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));
      outbox.stop();

      handler.mockClear();

      const replayed = await outbox.replay("consumer-1", "evt-2");

      expect(replayed).toBe(2);
      expect(handler).toHaveBeenCalledTimes(2);
    });

    it("should replay specific range", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["*"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const events: DomainEvent[] = [];
      for (let i = 1; i <= 5; i++) {
        const event: DomainEvent = {
          eventId: `evt-${i}`,
          eventType: "test",
          aggregateId: "agg-1",
          aggregateType: "test",
          payload: {},
          scope: sampleScope,
          timestamp: new Date(`2024-01-01T00:0${i}:00Z`).toISOString(),
        };
        events.push(event);
        await outbox.append(event);
      }

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));
      outbox.stop();

      handler.mockClear();

      const replayed = await outbox.replay("consumer-1", "evt-2", "evt-4");

      expect(replayed).toBe(3);
    });
  });

  describe("reconciliation", () => {
    it("should reconcile consumer state", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["*"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event1: DomainEvent = {
        eventId: "evt-1",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:00:00Z").toISOString(),
      };

      const event2: DomainEvent = {
        eventId: "evt-2",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:01:00Z").toISOString(),
      };

      await outbox.append(event1);
      await outbox.append(event2);

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));
      outbox.stop();

      handler.mockClear();

      const event3: DomainEvent = {
        eventId: "evt-3",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:02:00Z").toISOString(),
      };

      await outbox.append(event3);

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));
      outbox.stop();

      const result = await outbox.reconcile("consumer-1");

      expect(result.processed).toBe(0);
      expect(result.skipped).toBe(3);
      expect(result.failed).toBe(0);
    });

    it("should process missed events during reconciliation", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["*"],
        handler,
      };

      const event1: DomainEvent = {
        eventId: "evt-1",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:00:00Z").toISOString(),
      };

      await outbox.append(event1);

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));
      outbox.stop();

      outbox.registerConsumer(consumer);

      const event2: DomainEvent = {
        eventId: "evt-2",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date("2024-01-01T00:01:00Z").toISOString(),
      };

      await outbox.append(event2);

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));
      outbox.stop();

      const result = await outbox.reconcile("consumer-1");

      expect(result.processed).toBe(1); // Only event1 was missed
      expect(result.skipped).toBe(1); // Event2 was already delivered
    });
  });

  describe("dead letter retry", () => {
    it("should retry dead letter entry", async () => {
      let attempts = 0;
      const handler = vi.fn().mockImplementation(async () => {
        attempts++;
        if (attempts <= 3) {
          throw new Error("Error");
        }
      });

      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 600));

      const deadLetters = outbox.getDeadLetters();
      expect(deadLetters).toHaveLength(1);

      const success = await outbox.retryDeadLetter(deadLetters[0].entryId);

      expect(success).toBe(true);
      expect(outbox.getDeadLetters()).toHaveLength(0);
    });

    it("should mark dead letter as non-retryable after max attempts", async () => {
      const handler = vi.fn().mockRejectedValue(new Error("Error"));

      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["run.started"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event: DomainEvent = {
        eventId: "evt-1",
        eventType: "run.started",
        aggregateId: "run-1",
        aggregateType: "workflow_run",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event);
      outbox.start();

      await new Promise((resolve) => setTimeout(resolve, 600));

      const deadLetters = outbox.getDeadLetters();
      const deadLetter = deadLetters[0];

      for (let i = 0; i < 3; i++) {
        await outbox.retryDeadLetter(deadLetter.entryId);
      }

      const updated = outbox.getDeadLetters()[0];
      expect(updated.canRetry).toBe(false);
    });
  });

  describe("statistics", () => {
    it("should track outbox statistics", async () => {
      const handler = vi.fn().mockResolvedValue(undefined);
      const consumer: EventConsumer = {
        consumerId: "consumer-1",
        eventTypes: ["*"],
        handler,
      };

      outbox.registerConsumer(consumer);

      const event1: DomainEvent = {
        eventId: "evt-1",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      const event2: DomainEvent = {
        eventId: "evt-2",
        eventType: "test",
        aggregateId: "agg-1",
        aggregateType: "test",
        payload: {},
        scope: sampleScope,
        timestamp: new Date().toISOString(),
      };

      await outbox.append(event1);
      await outbox.append(event2);

      let stats = outbox.getStatistics();
      expect(stats.outbox.total).toBe(2);
      expect(stats.outbox.pending).toBe(2);
      expect(stats.consumers).toBe(1);

      outbox.start();
      await new Promise((resolve) => setTimeout(resolve, 150));

      stats = outbox.getStatistics();
      expect(stats.outbox.published).toBe(2);
      expect(stats.processedEvents).toBe(2);
    });
  });
});
