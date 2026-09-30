from __future__ import annotations

from .contracts import ChartPolicy, ChartTaskInput
from .errors import ChartError


def _comparison_backed_target_vs_peer(task: ChartTaskInput, artifacts: list[dict]) -> bool:
    comparison_ids = {artifact["artifact_id"] for artifact in artifacts if artifact["artifact_type"] == "comparison"}
    return any(
        target.visual_question == "target_vs_peer" and comparison_ids.intersection(target.artifact_ids)
        for target in task.visual_targets
    )


def validate_input(task: ChartTaskInput, artifacts: list[dict], policy: ChartPolicy) -> dict:
    if task.schema_version != "chart-task/2.0":
        raise ChartError("INP-001", "unsupported chart task schema", "input")
    if policy.ruleset_version != task.policy_ref:
        raise ChartError("POL-002", "task policy reference does not match loaded policy", "policy")
    wanted = {(ref.artifact_id, ref.version) for ref in task.artifact_refs if ref.required}
    received = {(artifact["artifact_id"], artifact["version"]) for artifact in artifacts}
    missing = wanted - received
    if missing:
        raise ChartError("DEP-004", f"required artifacts missing: {sorted(missing)!r}", "dependency")
    for artifact in artifacts:
        if artifact["run_id"] != task.run_id:
            raise ChartError("DAT-001", f"run_id mismatch for {artifact['artifact_id']}", "data_consistency")
        if artifact["status"] != "validated":
            raise ChartError("DAT-002", f"artifact {artifact['artifact_id']} is not validated", "data_consistency")
        artifact_scope = artifact.get("scope", {})
        if task.scope.snapshot_id and artifact_scope.get("snapshot_id") != task.scope.snapshot_id:
            raise ChartError("DAT-003", f"snapshot mismatch for {artifact['artifact_id']}", "data_consistency")
        if (
            task.scope.data_grain
            and artifact_scope.get("data_grain") != task.scope.data_grain
            and not (artifact["artifact_type"] == "metric" and _comparison_backed_target_vs_peer(task, artifacts))
        ):
            raise ChartError("DAT-004", f"grain mismatch for {artifact['artifact_id']}", "data_consistency")
        if task.scope.project_ids and not set(task.scope.project_ids).issubset(artifact_scope.get("project_ids", [])):
            raise ChartError("SCP-001", f"scope mismatch for {artifact['artifact_id']}", "scope")
    return {"overall_result": "pass", "checks": ["schema", "policy", "run_id", "scope", "snapshot", "grain"]}
