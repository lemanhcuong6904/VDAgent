import type { AgentReportView, StepSpecView } from "../../ui/agentReport";
import { explainWarning, reportTone } from "../../ui/agentReport";

const TONE_LABEL = { ok: "Hoàn tất", partial: "Hoàn tất một phần", error: "Không hoàn thành", ask: "Cần bạn chọn" } as const;
const STATE_LABEL: Record<string, string> = { rejected: "Bị từ chối", canceled: "Đã hủy", failed: "Không hoàn thành" };

function shortHash(hash: string | null): string {
  return hash ? hash.slice(0, 8) : "";
}

function RawJson({ raw }: { raw: string }) {
  return (
    <details className="card-raw">
      <summary>JSON gốc</summary>
      <pre className="mono">{raw}</pre>
    </details>
  );
}

/** What an agent answered an Orchestrator step, as a card: state, artifacts, limitations, error or question. */
export function AgentReportCard({ report, raw }: { report: AgentReportView; raw: string }) {
  const tone = reportTone(report);
  const label = tone === "error" ? (STATE_LABEL[report.state] ?? TONE_LABEL.error) : TONE_LABEL[tone];
  return (
    <div className={`agent-card agent-card-${tone}`}>
      <div className="card-head">
        <span className={`card-badge card-badge-${tone}`}>{label}</span>
        {report.step_id && <span className="card-chip mono">{report.step_id}</span>}
        {report.snapshot_id && (
          <span className="card-chip mono" title="Kỳ chốt và phiên bản cấu hình đã ghim">
            {report.snapshot_id}
            {report.semantic_config_version ? ` · ${report.semantic_config_version}` : ""}
          </span>
        )}
        {report.data_confidence && <span className="card-chip">độ tin cậy {report.data_confidence}</span>}
      </div>

      {report.error && (
        <div className="card-error">
          <span className="mono">{report.error.code}</span>
          {report.error.message && <span>: {report.error.message}</span>}
          {report.error.retryable && <span className="muted"> (có thể thử lại)</span>}
        </div>
      )}

      {report.question && (
        <div className="card-question">
          <div>{report.question.text}</div>
          <ul>
            {report.question.options.map((o) => (
              <li key={o.id}>
                <span className="mono">{o.id}</span> {o.label}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.artifact_refs.length > 0 && (
        <div className="card-section">
          <div className="card-title">Gói kết quả đã lưu</div>
          <ul className="card-artifacts">
            {report.artifact_refs.map((r) => (
              <li key={`${r.artifact_id}@${r.version}`}>
                <span className={`card-type card-type-${r.artifact_type}`}>{r.artifact_type}</span>
                <span className="mono">
                  {r.artifact_id}@{r.version}
                </span>
                {r.content_hash && (
                  <span className="muted mono" title={r.content_hash}>
                    {shortHash(r.content_hash)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.warnings.length > 0 && (
        <div className="card-section">
          <div className="card-title">Hạn chế cần biết</div>
          <ul className="card-warnings">
            {report.warnings.map((w) => {
              const view = explainWarning(w);
              return (
                <li key={w} title={w}>
                  <span className="card-code mono">{view.code}</span> {view.text === w ? "" : view.text}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <RawJson raw={raw} />
    </div>
  );
}

/** What the Orchestrator asked an agent to do, as a card instead of a JSON body. */
export function StepSpecCard({ view }: { view: StepSpecView }) {
  return (
    <div className="agent-card agent-card-task">
      <div className="card-head">
        <span className="card-badge card-badge-task">Orchestrator giao việc</span>
        <span className="card-chip mono">{view.stepId}</span>
        <span className="card-chip mono">{view.operation}</span>
        {view.deadlineS !== null && <span className="card-chip">hạn {view.deadlineS}s</span>}
      </div>
      {view.question && <div className="card-question-text">“{view.question}”</div>}
      <dl className="card-kv">
        {view.spec.map(([k, v]) => (
          <div key={k}>
            <dt className="mono">{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
        {view.snapshot && (
          <div>
            <dt>kỳ chốt</dt>
            <dd className="mono">
              {view.snapshot}
              {view.semantic ? ` · ${view.semantic}` : ""}
            </dd>
          </div>
        )}
        {view.scopeProjects.length > 0 && (
          <div>
            <dt>phạm vi trong phiếu</dt>
            <dd className="mono">{view.scopeProjects.join(", ")}</dd>
          </div>
        )}
      </dl>
      <RawJson raw={view.raw} />
    </div>
  );
}
