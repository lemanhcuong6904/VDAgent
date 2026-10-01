/**
 * M6: in-process consumer fan-out behind the durable OutboxPublisher. PostgreSQL owns durability
 * and claiming; EventOutbox owns per-consumer dedupe, checkpoints and dead letters.
 */
import type { AgentScope } from "./contracts/index.js";
import { type EventConsumer, EventOutbox } from "./event-outbox.js";
import type { OutboxDispatcher, OutboxEvent } from "./outbox.js";

const SYSTEM_SCOPE: AgentScope = {
  tenantId: "platform",
  workspaceId: "platform",
  actorId: "outbox",
  audience: "internal",
  taskId: "outbox",
  runId: "outbox",
  attemptId: "outbox.1",
  agentId: "platform.outbox",
  agentVersion: "1.0.0",
  policyRevision: "platform",
  fence: "1",
  traceId: "outbox",
};

/** Default consumer: one structured log line per published event (the previous behavior). */
export const logConsumer: EventConsumer = {
  consumerId: "log",
  eventTypes: ["*"],
  async handler(event) {
    process.stdout.write(
      `${JSON.stringify({
        message: "platform.outbox_published",
        outbox_id: event.eventId,
        run_id: event.aggregateId,
        event_type: event.eventType,
      })}\n`,
    );
  },
};

export function createOutboxFanout(consumers: readonly EventConsumer[] = [logConsumer]): {
  outbox: EventOutbox;
  dispatch: OutboxDispatcher;
} {
  const outbox = new EventOutbox();
  for (const consumer of consumers) outbox.registerConsumer(consumer);
  const dispatch: OutboxDispatcher = (event: OutboxEvent) =>
    outbox.deliver({
      eventId: String(event.id),
      eventType: event.event_type,
      aggregateId: event.run_id ?? "platform",
      aggregateType: "run",
      payload: event.payload,
      scope: SYSTEM_SCOPE,
      timestamp: new Date().toISOString(),
    });
  return { outbox, dispatch };
}
