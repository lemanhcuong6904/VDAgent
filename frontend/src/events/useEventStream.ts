import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { queryKeys } from "../api/keys";
import { SERVER_EVENT_NAMES, type ServerEvent } from "../api/types";
import { applyEvent } from "./applyEvent";

export type StreamState = "connecting" | "open" | "reconnecting";

/** Delay before re-creating an EventSource the browser gave up on (e.g. BE down at connect). */
const RECONNECT_DELAY_MS = 3000;
const REPORT_ID = /\brp_[0-9a-f]{12}\b/;

/**
 * One EventSource per selected user. The server persists a per-user cursor, so reconnects
 * request events after the last event applied by this browser.
 */
export function useEventStream(userId: string | null): StreamState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<StreamState>("connecting");

  useEffect(() => {
    if (!userId) return;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;
    let disposed = false;
    let cursor = 0;

    const connect = () => {
      const url = `/api/events?user_id=${encodeURIComponent(userId)}&after=${cursor}`;
      const es = new EventSource(url);
      source = es;
      es.onopen = () => {
        setState("open");
        void queryClient.invalidateQueries();
      };
      es.onerror = () => {
        if (disposed) return;
        setState("reconnecting");
        // CONNECTING → the browser retries by itself; CLOSED → it gave up, so retry manually.
        if (es.readyState === EventSource.CLOSED) {
          es.close();
          retryTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
      for (const name of SERVER_EVENT_NAMES) {
        es.addEventListener(name, (msg) => {
          let data: unknown;
          try {
            data = JSON.parse((msg as MessageEvent<string>).data);
          } catch {
            console.warn(`vdagent: malformed ${name} event`, msg);
            return;
          }
          const ev = { event: name, data } as ServerEvent;
          const eventId = Number((msg as MessageEvent<string>).lastEventId);
          if (Number.isSafeInteger(eventId) && eventId > cursor) cursor = eventId;
          applyEvent(queryClient, ev);
          // Reports are not part of the event protocol; refresh the list when one is mentioned.
          if (ev.event === "message.appended" && REPORT_ID.test(ev.data.message.content)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.reports });
          }
        });
      }
    };

    setState("connecting");
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      source?.close();
    };
  }, [userId, queryClient]);

  return state;
}
