import { useReports, useTask } from "../../api/queries";
import { artifactIds, artifactKind } from "../../ui/artifacts";
import { formatDateTime } from "../../ui/format";
import { useUi } from "../../ui/UiContext";
import { ArtifactEnvelopeView } from "./ArtifactEnvelopeView";
import { ChartView } from "./ChartView";
import { DatasetTable } from "./DatasetTable";
import { ReportView } from "./ReportView";
import { TaskTree } from "./TaskTree";

/** Right column: the selected task's invocation tree, or an artifact viewer. */
export function Inspector({ taskId }: { taskId: string | null }) {
  const { tab, setTab } = useUi();
  return (
    <div className="inspector-inner">
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "task"}
          className={`tab${tab === "task" ? " active" : ""}`}
          onClick={() => setTab("task")}
        >
          Task
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "artifact"}
          className={`tab${tab === "artifact" ? " active" : ""}`}
          onClick={() => setTab("artifact")}
        >
          Artifacts
        </button>
      </div>
      <div className="inspector-body">
        {tab === "task" ? (
          taskId ? (
            <TaskTree taskId={taskId} />
          ) : (
            <div className="muted small">No tasks yet. Message an agent to start one.</div>
          )
        ) : (
          <ArtifactPanel taskId={taskId} />
        )}
      </div>
    </div>
  );
}

function ArtifactPanel({ taskId }: { taskId: string | null }) {
  const { artifactId, recentArtifacts, openArtifact } = useUi();
  const reports = useReports();
  const task = useTask(taskId);
  const taskArtifacts = [
    ...new Set(
      (task.data?.invocations ?? []).flatMap((inv) =>
        artifactIds([inv.inbound_text, inv.result_text, inv.error].filter((text): text is string => Boolean(text)).join("\n")),
      ),
    ),
  ];
  return (
    <div className="artifact-panel">
      {taskArtifacts.length > 0 && (
        <section>
          <div className="section-label">Task Artifacts</div>
          <div className="recent-artifacts">
            {taskArtifacts.map((id) => (
              <button
                key={id}
                type="button"
                className={`artifact-chip artifact-${artifactKind(id)}${id === artifactId ? " active" : ""}`}
                onClick={() => openArtifact(id)}
              >
                {id}
              </button>
            ))}
          </div>
        </section>
      )}
      {recentArtifacts.length > 0 && (
        <div className="recent-artifacts">
          {recentArtifacts.map((id) => (
            <button
              key={id}
              type="button"
              className={`artifact-chip artifact-${artifactKind(id)}${id === artifactId ? " active" : ""}`}
              onClick={() => openArtifact(id)}
            >
              {id}
            </button>
          ))}
        </div>
      )}
      {artifactId ? (
        <ArtifactViewer id={artifactId} />
      ) : (
        <div className="muted small">Click a ds_…, ch_… or rp_… id in any chat to open it here.</div>
      )}
      <section className="reports-list">
        <div className="section-label">Reports</div>
        {reports.isError && <div className="error-text">{reports.error.message}</div>}
        {reports.data?.length === 0 && <div className="muted small">No reports yet.</div>}
        <ul>
          {reports.data?.map((r) => (
            <li key={r.id}>
              <button type="button" className="report-item" onClick={() => openArtifact(r.id)}>
                <span className="report-title">{r.title}</span>
                <span className="muted small">{formatDateTime(r.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ArtifactViewer({ id }: { id: string }) {
  switch (artifactKind(id)) {
    case "dataset":
      return <DatasetTable key={id} id={id} />;
    case "chart":
      return <ChartView key={id} id={id} />;
    case "envelope":
      return <ArtifactEnvelopeView key={id} id={id} version={1} />;
    case "report":
      return <ReportView key={id} id={id} />;
  }
}
