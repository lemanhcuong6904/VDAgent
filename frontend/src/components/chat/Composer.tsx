import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { queryKeys } from "../../api/keys";
import { useApi, useTask } from "../../api/queries";
import type { AgentDTO } from "../../api/types";
import { composerPlaceholder } from "../../ui/composerHint";
import { useUi } from "../../ui/UiContext";
import { getConversationRefreshInterval } from "./messageRefresh";

/** Posts a human message into the agent's chat (creates a task). */
export function Composer({ agent }: { agent: AgentDTO }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const { selectTask } = useUi();
  const [text, setText] = useState("");
  const [submittedTaskId, setSubmittedTaskId] = useState<string | null>(null);
  const { data: submittedTaskData, refetch: refetchSubmittedTask } = useTask(submittedTaskId);
  const refreshInterval = getConversationRefreshInterval(submittedTaskData?.task.status);

  useEffect(() => {
    if (!submittedTaskId) return;

    const refreshMessages = () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.messages(agent.name) });

    void refreshMessages();
    if (!refreshInterval) {
      setSubmittedTaskId(null);
      return;
    }

    const timer = window.setInterval(() => {
      void refreshMessages();
      void refetchSubmittedTask();
    }, refreshInterval);
    return () => window.clearInterval(timer);
  }, [agent.name, queryClient, refreshInterval, refetchSubmittedTask, submittedTaskId]);


  const post = useMutation({
    mutationFn: (content: string) => api.postMessage(agent.name, content),
    onSuccess: (res) => {
      setText("");
      setSubmittedTaskId(res.task_id);
      selectTask(res.task_id, agent.name);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      void queryClient.invalidateQueries({ queryKey: queryKeys.messages(agent.name) });
    },
  });

  const content = text.trim();
  const canSend = content.length > 0 && !post.isPending;

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (canSend) post.mutate(content);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        rows={2}
        value={text}
        placeholder={composerPlaceholder(agent.name)}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <button type="submit" className="btn send-btn" disabled={!canSend} title="Send">
        {post.isPending ? <span className="spinner small" /> : "➤"}
      </button>
      {post.error && <div className="composer-error error-text">{post.error.message}</div>}
    </form>
  );
}
