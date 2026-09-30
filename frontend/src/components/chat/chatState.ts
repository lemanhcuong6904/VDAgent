export type ChatPanelState = "loading" | "error" | "empty" | "content";

export function getChatPanelState({
  isPending,
  isError,
  messageCount,
  pendingCount,
  hasSummary,
}: {
  isPending: boolean;
  isError: boolean;
  messageCount: number;
  pendingCount: number;
  hasSummary: boolean;
}): ChatPanelState {
  if (isPending) return "loading";
  if (isError) return "error";
  if (messageCount === 0 && pendingCount === 0 && !hasSummary) return "empty";
  return "content";
}
