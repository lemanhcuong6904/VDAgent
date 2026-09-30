import { useTasks } from "../api/queries";
import { agentColor } from "../ui/artifacts";
import { formatRelative } from "../ui/format";
import { taskStatusLabel } from "../ui/taskStatus";
import { useUi } from "../ui/UiContext";
import { StatusIcon } from "./StatusIcon";

function conversationPreview(preview: string | null | undefined, agent: string): string {
  const text = preview?.replace(/\s+/g, " ").trim();
  return text || `Conversation with ${agent}`;
}

/** Recent conversations; click shows that conversation in the chat and Inspector. */
export function TaskList({ activeTaskId }: { activeTaskId: string | null }) {
  const tasks = useTasks();
  const { selectTask } = useUi();
  return (
    <section className="sidebar-section tasks-section">
      <div className="section-label">Conversations</div>
      {tasks.isError && <div className="error-text">{tasks.error.message}</div>}
      {tasks.data?.length === 0 && <div className="muted small">No conversations yet.</div>}
      <ul className="task-list">
        {tasks.data?.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              className={`task-item${t.id === activeTaskId ? " selected" : ""}`}
              onClick={() => selectTask(t.id, t.root_agent)}
              title={`${conversationPreview(t.preview, t.root_agent)} · ${t.id} · ${taskStatusLabel(t)}`}
            >
              <StatusIcon status={t.status} />
              <span className="task-preview">{conversationPreview(t.preview, t.root_agent)}</span>
              <span className="task-agent" style={{ color: agentColor(t.root_agent) }}>
                {t.root_agent}
              </span>
              <span className="task-time muted">{formatRelative(t.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
