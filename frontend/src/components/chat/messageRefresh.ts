import type { TaskStatus } from "../../api/types";

export const CONVERSATION_REFRESH_MS = 750;

/** Keep the conversation in sync while a newly submitted task is still producing messages. */
export function getConversationRefreshInterval(status: TaskStatus | undefined): number | false {
  return status === "completed" || status === "failed" || status === "cancelled"
    ? false
    : CONVERSATION_REFRESH_MS;
}
