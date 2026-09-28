import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { browserAuthHeaders } from "../api/auth";
import { queryKeys } from "../api/keys";
import { SERVER_EVENT_NAMES } from "../api/types";
import { applyEvent } from "./applyEvent";
import { parseServerEvent } from "./parseEvent";

export type StreamState = "connecting" | "open" | "reconnecting";

/** Delay before retrying when the backend closed or rejected the stream request. */
const RECONNECT_DELAY_MS = 3000;
const REPORT_ID = /\brp_[0-9a-f]{12}\b/;

export interface EventStreamRequest {
  url: string;
  init: RequestInit;
}

/** Build a fetch-based SSE request so Authorization can be sent (EventSource cannot set it). */
export function buildEventStreamRequest(userId: string, cursor: number): EventStreamRequest {
  const params = new URLSearchParams({ user_id: userId, after: String(cursor) });
  return {
    url: `/api/events?${params.toString()}`,
    init: {
      method: "GET",
      headers: {
        Accept: "text/event-stream",
        ...browserAuthHeaders(userId),
        "Last-Event-ID": String(cursor),
      },
      credentials: "same-origin",
    },
  };
}

export interface SseMessage {
  id?: string;
  event: string;
  data: string;
}

/** Parse one complete SSE frame. Comment and extension fields are ignored per the SSE format. */
export function parseSseBlock(block: string): SseMessage | undefined {
  let id: string | undefined;
  let event = "message";
  const data: string[] = [];

  for (const line of block.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id" && !value.includes("\0")) id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  if (!data.length) return undefined;
  return { ...(id !== undefined && { id }), event, data: data.join("\n") };
}

/** Read and dispatch complete frames while preserving UTF-8 and frame boundaries across chunks. */
export async function consumeEventStream(
  body: ReadableStream<Uint8Array>,
  onMessage: (message: SseMessage) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      pending = pending.replace(/\r\n?/g, "\n");
      let boundary = pending.indexOf("\n\n");
      while (boundary !== -1) {
        const block = pending.slice(0, boundary);
        pending = pending.slice(boundary + 2);
        const message = parseSseBlock(block);
        if (message) onMessage(message);
        boundary = pending.indexOf("\n\n");
      }
      if (done) {
        const message = parseSseBlock(pending);
        if (message) onMessage(message);
        return;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** One authenticated streaming fetch per selected user, replaying from the last applied event. */
export function useEventStream(userId: string | null): StreamState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<StreamState>("connecting");

  useEffect(() => {
    if (!userId) return;
    let controller: AbortController | undefined;
    let retryTimer: number | undefined;
    let disposed = false;
    let cursor = 0;

    const connect = async () => {
      controller = new AbortController();
      const currentController = controller;
      const request = buildEventStreamRequest(userId, cursor);
      try {
        const response = await fetch(request.url, {
          ...request.init,
          signal: currentController.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`event stream request failed (${response.status})`);
        }
        if (disposed) return;
        setState("open");
        void queryClient.invalidateQueries();
        await consumeEventStream(response.body, (message) => {
          const eventId = Number(message.id);
          // Advance even for a malformed payload so one bad durable event cannot pin replay.
          if (message.id !== undefined && Number.isSafeInteger(eventId) && eventId > cursor) {
            cursor = eventId;
          }
          const eventName = SERVER_EVENT_NAMES.find((name) => name === message.event);
          if (!eventName) {
            return;
          }
          let data: unknown;
          try {
            data = JSON.parse(message.data);
          } catch {
            console.warn(`vdagent: malformed ${message.event} event`);
            return;
          }
          const event = parseServerEvent(eventName, data);
          if (!event) {
            console.warn(`vdagent: ignoring ${eventName} event with an unexpected shape`);
            return;
          }
          applyEvent(queryClient, event);
          // Reports are not part of the event protocol; refresh the list when one is mentioned.
          if (event.event === "message.appended" && REPORT_ID.test(event.data.message.content)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.reports });
          }
        });
      } catch (error) {
        if (!disposed && !(error instanceof DOMException && error.name === "AbortError")) {
          setState("reconnecting");
        }
      } finally {
        if (!disposed) {
          currentController.abort();
          setState("reconnecting");
          retryTimer = window.setTimeout(() => void connect(), RECONNECT_DELAY_MS);
        }
      }
    };

    setState("connecting");
    void connect();
    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      controller?.abort();
    };
  }, [userId, queryClient]);

  return state;
}
