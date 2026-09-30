import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMessages } from "../../api/queries";
import type { AgentDTO, MessageDTO, ToolCallDTO } from "../../api/types";
import { CompactedDivider } from "./CompactedDivider";
import { Composer } from "./Composer";
import { MessageItem, PendingItem } from "./MessageItem";
import { getChatPanelState } from "./chatState";

/** Distance (px) from an edge that still counts as "at" that edge. */
const EDGE_PX = 80;

/** One agent's stack, optionally focused on a single task. */
export function ChatPane({ agent, taskId }: { agent: AgentDTO; taskId: string | null }) {
  const query = useMessages(agent.name);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  const [showCompacted, setShowCompacted] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousTaskId = useRef(taskId);

  const pages = query.data?.pages;
  const newest = pages?.[0];

  const { messages, toolCalls, toolResults, compactedTasks, lastCompactedSeq } = useMemo(() => {
    const byId = new Map<number, MessageDTO>();
    // pages: newest first; each page ascending by seq.
    for (const page of [...(pages ?? [])].reverse()) for (const m of page.messages) byId.set(m.id, m);
    const sorted = [...byId.values()].sort((a, b) => a.seq - b.seq);
    const visible = taskId ? sorted.filter((m) => m.task_id === taskId) : sorted;
    const calls = new Map<string, ToolCallDTO>();
    const results = new Map<string, MessageDTO>();
    const tasks = new Set<string>();
    let lastCompacted: number | null = null;
    for (const m of visible) {
      for (const c of m.tool_calls ?? []) calls.set(c.id, c);
      if (m.role === "tool" && m.tool_call_id) results.set(m.tool_call_id, m);
      if (m.compacted) {
        tasks.add(m.task_id);
        lastCompacted = m.seq;
      }
    }
    return {
      messages: visible,
      toolCalls: calls,
      toolResults: results,
      compactedTasks: tasks.size,
      lastCompactedSeq: lastCompacted,
    };
  }, [pages, taskId]);

  const summary = taskId ? null : newest?.summary ?? null;
  const pending = taskId ? [] : newest?.pending ?? [];
  const hasDivider = lastCompactedSeq !== null || Boolean(summary);
  // While compacted history is collapsed, don't page through hidden (compacted) history.
  const canAutoLoad = showCompacted || !messages[0]?.compacted;
  const panelState = getChatPanelState({
    isPending: query.isPending,
    isError: query.isError,
    messageCount: messages.length,
    pendingCount: pending.length,
    hasSummary: hasDivider,
  });

  const loadOlder = () => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  };

  // Scroll management: start at the bottom, follow new messages while at the bottom,
  // and keep the viewport anchored when older pages are prepended.
  const stickToBottom = useRef(true);
  const distanceFromBottom = useRef(0);
  const prevOldestSeq = useRef<number | undefined>(undefined);
  const initialized = useRef(false);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    distanceFromBottom.current = el.scrollHeight - el.scrollTop;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < EDGE_PX;
    if (el.scrollTop < EDGE_PX && canAutoLoad) loadOlder();
  };

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !query.data) return;
    const oldest = messages[0]?.seq;
    if (previousTaskId.current !== taskId) {
      previousTaskId.current = taskId;
      el.scrollTop = el.scrollHeight;
      initialized.current = true;
      stickToBottom.current = true;
      prevOldestSeq.current = oldest;
      distanceFromBottom.current = el.scrollHeight - el.scrollTop;
      return;
    }
    if (!initialized.current) {
      el.scrollTop = el.scrollHeight;
      initialized.current = true;
    } else if (oldest !== undefined && prevOldestSeq.current !== undefined && oldest < prevOldestSeq.current) {
      el.scrollTop = el.scrollHeight - distanceFromBottom.current;
    } else if (stickToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
    prevOldestSeq.current = oldest;
    distanceFromBottom.current = el.scrollHeight - el.scrollTop;
  });

  // History shorter than the viewport never scrolls, so load older pages until it overflows.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !canAutoLoad || !hasNextPage || isFetchingNextPage) return;
    if (el.scrollHeight <= el.clientHeight + EDGE_PX) void fetchNextPage();
  }, [messages.length, taskId, canAutoLoad, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const divider = (
    <CompactedDivider
      key="compacted-divider"
      summary={summary}
      taskCount={compactedTasks}
      moreOlder={Boolean(hasNextPage)}
      expanded={showCompacted}
      onToggle={() => setShowCompacted((v) => !v)}
    />
  );

  const items: ReactNode[] = [];
  if (hasDivider && lastCompactedSeq === null) items.push(divider);
  for (const m of messages) {
    if (!m.compacted || showCompacted) {
      items.push(
        <MessageItem
          key={m.id}
          message={m}
          agent={agent.name}
          toolCalls={toolCalls}
          toolResults={toolResults}
        />,
      );
    }
    if (m.seq === lastCompactedSeq) items.push(divider);
  }

  return (
    <div className="chat-pane">

      <div className={`chat-scroll chat-state-${panelState}`} ref={scrollRef} onScroll={onScroll}>
        {hasNextPage && (
          <div className="load-older">
            {isFetchingNextPage ? (
              <span className="muted small">
                <span className="spinner small" /> loading older messages…
              </span>
            ) : (
              <button type="button" className="btn btn-ghost small" onClick={loadOlder}>
                Load older messages
              </button>
            )}
          </div>
        )}
        {query.isPending && <div className="chat-empty muted">Loading…</div>}
        {query.isError && <div className="chat-empty error-text">{query.error.message}</div>}
        {query.isSuccess && messages.length === 0 && pending.length === 0 && !hasDivider && (
          <div className="chat-empty muted">
            {taskId ? "No chat messages for this task." : <>No messages yet. Ask <strong>{agent.name}</strong> something below.</>}
          </div>
        )}
        <div className="message-list">
          {items}
          {pending.map((p) => (
            <PendingItem key={p.invocation_id} pending={p} />
          ))}
          {agent.busy && (
            <div className="working muted small">
              <span className="spinner small" /> {agent.name} is working…
            </div>
          )}
        </div>
      </div>

      <Composer agent={agent} />
    </div>
  );
}
