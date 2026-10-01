import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { ApiError } from "../../api/client";
import { queryKeys } from "../../api/keys";
import { useApi, useRunView, useTaskRun } from "../../api/queries";
import type { RunViewDTO } from "../../api/types";
import { formatDateTime, truncate } from "../../ui/format";
import {
  costRows,
  formatBytes,
  formatCost,
  formatMs,
  orderGraph,
  outcomeLabel,
} from "../../ui/runView";

/**
 * Durable-run view for the selected task (M12.3). Everything shown comes from the
 * server's authorized `/api/v1/runs/:id/view` projection; controls render only when
 * `permissions` allows them.
 */
export function RunPanel({ taskId }: { taskId: string | null }) {
  const link = useTaskRun(taskId);
  const runId = link.data?.run_id ?? null;
  const view = useRunView(runId);

  if (!taskId) return <div className="muted small">Select a task to see its run.</div>;
  if (link.isPending) return <div className="muted small">Loading run…</div>;
  if (link.isError) {
    const missing = link.error instanceof ApiError && link.error.code === "run_missing";
    return (
      <div className="muted small">
        {missing ? "This task predates the durable run ledger." : link.error.message}
      </div>
    );
  }
  if (view.isPending) return <div className="muted small">Loading run…</div>;
  if (view.isError) return <div className="error-text">{view.error.message}</div>;
  return <RunDetail view={view.data} />;
}

function RunDetail({ view }: { view: RunViewDTO }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => api.cancelRun(view.run.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.runView(view.run.id) }),
  });
  const graph = useMemo(() => orderGraph(view.graph), [view.graph]);
  const outcome = outcomeLabel(view);

  return (
    <div className="run-panel">
      <section>
        <div className="run-header">
          <span className="mono">{view.run.id}</span>
          <span className={`run-status run-status-${view.run.status}`}>{view.run.status}</span>
          {view.permissions.canCancel && (
            <button
              type="button"
              className="btn btn-danger small"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Cancel run
            </button>
          )}
        </div>
        <div className="muted small">
          {view.run.workflowId}@{view.run.workflowVersion} · started{" "}
          {formatDateTime(view.run.createdAt)}
          {view.run.durationMs !== null && ` · ${formatMs(view.run.durationMs)}`}
          {view.run.cancelRequested && " · cancel requested"}
        </div>
        <div className={`run-outcome run-outcome-${outcome.tone}`} role="status">
          {outcome.text}
        </div>
        {cancel.isError && <div className="error-text">{cancel.error.message}</div>}
        {view.truncated && (
          <div className="muted small">Timeline truncated; the event log has more entries.</div>
        )}
      </section>

      <section>
        <div className="section-label">Graph</div>
        {graph.length === 0 ? (
          <div className="muted small">No steps recorded.</div>
        ) : (
          <ul className="run-graph">
            {graph.map(({ node, depth }) => (
              <li key={node.id} style={{ paddingLeft: depth * 14 }}>
                <span className={`run-status run-status-${node.status}`}>{node.status}</span>{" "}
                <span className="small">{node.kind}</span>{" "}
                <span className="mono">{node.agentId ?? node.capability ?? node.id}</span>
                {node.attempt > 0 && <span className="muted small"> · retry {node.attempt}</span>}
                {node.durationMs !== null && (
                  <span className="muted small"> · {formatMs(node.durationMs)}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {view.approvals.length > 0 && (
        <section>
          <div className="section-label">Approvals</div>
          <ul className="run-list">
            {view.approvals.map((approval) => (
              <li key={approval.stepId}>
                <span className={`run-approval run-approval-${approval.state}`}>
                  {approval.state}
                </span>{" "}
                <span className="mono">{approval.stepId}</span>
                {approval.waitedMs !== null && (
                  <span className="muted small"> · waited {formatMs(approval.waitedMs)}</span>
                )}
              </li>
            ))}
          </ul>
          {!view.permissions.canDecideApproval &&
            view.approvals.some((a) => a.state === "pending") && (
              <div className="muted small">Pending approvals are decided by the host approver.</div>
            )}
        </section>
      )}

      <section>
        <div className="section-label">Artifacts</div>
        {view.artifacts.length === 0 ? (
          <div className="muted small">No artifacts.</div>
        ) : (
          <ul className="run-list">
            {view.artifacts.map((artifact) => (
              <li key={artifact.id}>
                <span className="mono">{artifact.id}</span>{" "}
                <span className="small">
                  {artifact.kind} v{artifact.version} · {artifact.status} ·{" "}
                  {formatBytes(artifact.bytes)}
                </span>{" "}
                <span className={artifact.verified ? "run-verified" : "run-unverified"}>
                  {artifact.verified ? "hash verified" : "not verified"}
                </span>
                {artifact.sha256 && (
                  <div className="mono muted" title={artifact.sha256}>
                    sha256 {artifact.sha256.slice(0, 16)}…
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <div className="section-label">Evidence</div>
        <div className="small">
          {view.evidence.counts.verified} verified · {view.evidence.counts.unverified} unverified ·{" "}
          {view.evidence.counts.unavailable} unavailable
        </div>
        {view.evidence.items.length > 0 && (
          <ul className="run-list">
            {view.evidence.items.map((item) => (
              <li key={item.id}>
                <span className={`run-evidence run-evidence-${item.verification}`}>
                  {item.verification}
                </span>{" "}
                <span className="small">{item.kind}</span>{" "}
                <span className="mono">{truncate(item.ref, 60)}</span>
              </li>
            ))}
          </ul>
        )}
        {view.evidence.truncated && (
          <div className="muted small">Showing the first entries only.</div>
        )}
      </section>

      <section>
        <div className="section-label">Cost</div>
        <div className="small">
          {formatCost(view.cost.totals.estimatedCost)} estimated · {view.cost.totals.inputTokens} in
          / {view.cost.totals.outputTokens} out tokens · {view.cost.totals.records} calls
        </div>
        {costRows(view.cost.byModel).length > 0 && (
          <table className="run-cost">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Calls</th>
                <th scope="col">Tokens</th>
                <th scope="col">Cost</th>
              </tr>
            </thead>
            <tbody>
              {costRows(view.cost.byModel).map(({ key, totals }) => (
                <tr key={key}>
                  <td className="mono">{key}</td>
                  <td>{totals.records}</td>
                  <td>{totals.inputTokens + totals.outputTokens}</td>
                  <td>{formatCost(totals.estimatedCost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {view.errors.length > 0 && (
        <section>
          <div className="section-label">Errors</div>
          <ul className="run-list">
            {view.errors.map((failure) => (
              <li key={`${failure.source}:${failure.ref}:${failure.at}`} className="error-text">
                <span className="mono">
                  {failure.source}:{failure.ref}
                </span>{" "}
                {failure.message}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
