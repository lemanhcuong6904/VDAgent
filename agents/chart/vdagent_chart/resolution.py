"""Exact artifact resolution into the typed context used by the chart pipeline."""

from __future__ import annotations

from .contracts import ChartPolicy, ChartTaskInput, ResolvedChartContext
from .errors import ChartError
from .ports import ArtifactStorePort
from .schema import normalize_artifact


def resolve_context(task: ChartTaskInput, store: ArtifactStorePort, policy: ChartPolicy) -> ResolvedChartContext:
    if policy.ruleset_version != task.policy_ref:
        raise ChartError("POL-002", "task policy reference does not match loaded policy", "policy")
    artifacts = []
    for ref in task.artifact_refs:
        try:
            raw = store.get_exact(ref)
        except ChartError as exc:
            raise ChartError(exc.code, exc.message, exc.category, exc.retryable, {"artifact_id": ref.artifact_id, "version": ref.version}) from exc
        artifacts.append(normalize_artifact(raw))
    for artifact in artifacts:
        if artifact.run_id != task.run_id:
            raise ChartError("DAT-001", f"run_id mismatch for {artifact.artifact_id}", "data_consistency")
        if artifact.status != "validated":
            raise ChartError("DAT-002", f"artifact {artifact.artifact_id} is not validated", "data_consistency")
        if artifact.scope.snapshot_id != task.scope.snapshot_id:
            raise ChartError("DAT-003", f"snapshot mismatch for {artifact.artifact_id}", "data_consistency")
        if task.scope.project_ids and not set(task.scope.project_ids).issubset(artifact.scope.project_ids):
            raise ChartError("SCP-001", f"scope mismatch for {artifact.artifact_id}", "scope")
    return ResolvedChartContext(task, policy, tuple(artifacts), {"overall_result": "pass", "checks": ["schema", "policy", "exact_refs", "run_id", "scope", "snapshot"]})
