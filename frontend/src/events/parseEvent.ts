import type { ServerEvent, ServerEventName } from "../api/types";

/**
 * Check the fields `applyEvent` reads, and nothing more (M12.6).
 * Unknown extra fields pass through so a newer server can add data without breaking
 * an older UI; an event missing a field the reducer needs is dropped rather than
 * crashing the reducer or writing a malformed row into the cache.
 */
export function parseServerEvent(name: ServerEventName, data: unknown): ServerEvent | undefined {
  if (!isRecord(data)) return undefined;
  switch (name) {
    case "message.appended":
      return isString(data.agent) &&
        isRecord(data.message) &&
        isNumber(data.message.id) &&
        isNumber(data.message.seq) &&
        isString(data.message.content)
        ? accept(name, data)
        : undefined;
    case "invocation.updated":
      return isRecord(data.invocation) &&
        isString(data.invocation.id) &&
        isString(data.invocation.task_id) &&
        isString(data.invocation.agent) &&
        isString(data.invocation.status)
        ? accept(name, data)
        : undefined;
    case "task.updated":
      return isRecord(data.task) && isString(data.task.id) && isString(data.task.status)
        ? accept(name, data)
        : undefined;
    case "agent.status":
      return isString(data.agent) ? accept(name, data) : undefined;
    default:
      return undefined;
  }
}

/** The guard above has checked the fields the reducer reads; the rest is opaque by design. */
function accept(name: ServerEventName, data: Record<string, unknown>): ServerEvent {
  return { event: name, data } as unknown as ServerEvent;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
