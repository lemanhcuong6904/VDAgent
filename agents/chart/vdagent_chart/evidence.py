"""Map a visual target to the exact validated artifacts that support it."""

from __future__ import annotations

from .contracts import EvidenceBinding, ResolvedChartContext
from .errors import ChartError


def build_evidence_map(context: ResolvedChartContext) -> dict[str, EvidenceBinding]:
    by_id = {artifact.artifact_id: artifact for artifact in context.artifacts}
    bindings: dict[str, EvidenceBinding] = {}
    for target in context.task.visual_targets:
        selected = [by_id[artifact_id] for artifact_id in target.artifact_ids if artifact_id in by_id]
        metrics = tuple(item.artifact_id for item in selected if item.artifact_type == "metric")
        evidence = tuple(item.artifact_id for item in selected if item.artifact_type == "evidence")
        insights = tuple(item.artifact_id for item in selected if item.artifact_type == "insight")
        comparisons = tuple(item.artifact_id for item in selected if item.artifact_type == "comparison")
        if not metrics:
            raise ChartError("DEP-005", f"target {target.target_id} requires a metric artifact", "dependency")
        if target.visual_question == "target_vs_peer" and not comparisons:
            raise ChartError("DEP-005", f"target {target.target_id} requires a comparison artifact", "dependency")
        bindings[target.target_id] = EvidenceBinding(target.target_id, metrics, evidence, insights, comparisons)
    return bindings
