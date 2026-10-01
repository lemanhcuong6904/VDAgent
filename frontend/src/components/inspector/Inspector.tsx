import { useEffect, useRef, useState } from "react";
import { useReports } from "../../api/queries";
import { formatDateTime } from "../../ui/format";
import { useUi } from "../../ui/UiContext";
import { ReportView } from "./ReportView";
import { TaskTree } from "./TaskTree";

/** Right column: the selected task activity or the saved report list. */
export function Inspector({ taskId }: { taskId: string | null }) {
  const { tab, setTab } = useUi();
  return (
    <div className="inspector-inner">
      <header className="inspector-header">
        <span className="eyebrow">Run detail</span>
        <span className="inspector-hint">{tab === "task" ? "Task activity" : "Reports"}</span>
      </header>
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
          <ArtifactPanel />
        )}
      </div>
    </div>
  );
}

function ArtifactPanel() {
  const reports = useReports();
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (selectedReportId && dialog && !dialog.open) dialog.showModal();
  }, [selectedReportId]);

  return (
    <div className="artifact-panel">
      <section className="reports-list">
        <div className="section-label">Reports</div>
        {reports.isError && <div className="error-text">{reports.error.message}</div>}
        {reports.data?.length === 0 && <div className="muted small">No reports yet.</div>}
        <ul>
          {reports.data?.map((r) => (
            <li key={r.id}>
              <button type="button" className="report-item" onClick={() => setSelectedReportId(r.id)}>
                <span className="report-title">{r.title}</span>
                <span className="muted small">{formatDateTime(r.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      {selectedReportId && (
        <dialog
          ref={dialogRef}
          className="report-dialog"
          aria-label="Report details"
          onClose={() => setSelectedReportId(null)}
          onClick={(event) => {
            if (event.target === event.currentTarget) dialogRef.current?.close();
          }}
        >
          <div className="report-dialog-toolbar">
            <button
              type="button"
              className="report-dialog-close"
              aria-label="Close report"
              onClick={() => dialogRef.current?.close()}
            >
              &times;
            </button>
          </div>
          <div className="report-dialog-content">
            <ReportView key={selectedReportId} id={selectedReportId} />
          </div>
        </dialog>
      )}
    </div>
  );
}
