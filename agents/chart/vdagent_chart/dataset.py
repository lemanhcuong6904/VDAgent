from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import EvidenceBinding, ResolvedChartContext, VisualTarget
from .errors import ChartError


def _metric_for(target: VisualTarget, artifacts: list[dict]) -> dict:
    allowed = set(target.artifact_ids)
    for artifact in artifacts:
        if artifact["artifact_type"] == "metric" and (not allowed or artifact["artifact_id"] in allowed):
            return artifact
    raise ChartError("DEP-005", f"no metric artifact available for target {target.target_id}", "dependency")


def _comparison_for(target: VisualTarget, artifacts: list[dict]) -> dict:
    allowed = set(target.artifact_ids)
    for artifact in artifacts:
        if artifact["artifact_type"] == "comparison" and (not allowed or artifact["artifact_id"] in allowed):
            return artifact
    raise ChartError("DEP-005", f"no comparison artifact available for target {target.target_id}", "dependency")


def _typed_records(context: ResolvedChartContext, binding: EvidenceBinding) -> tuple[VisualTarget, list[dict], dict[str, Any]]:
    artifacts = {artifact.artifact_id: artifact for artifact in context.artifacts}
    target = next(item for item in context.task.visual_targets if item.target_id == binding.target_id)
    if target.visual_question == "target_vs_peer" and binding.comparison_ids:
        source = artifacts[binding.comparison_ids[0]].payload
        return target, list(source["display_records"]), source
    source = artifacts[binding.metric_ids[0]].payload
    return target, list(source["records"]), source


def assemble_dataset(
    target: VisualTarget | ResolvedChartContext,
    artifacts: list[dict] | EvidenceBinding,
    decision: dict[str, Any],
) -> dict[str, Any]:
    if decision.get("top_n") is not None:
        raise ChartError("DAT-006", "top-N is not enabled by the demo policy", "data")
    if isinstance(target, ResolvedChartContext):
        if not isinstance(artifacts, EvidenceBinding):
            raise TypeError("typed dataset assembly requires an EvidenceBinding")
        _, records, source = _typed_records(target, artifacts)
    elif target.visual_question == "target_vs_peer":
        if not isinstance(artifacts, list):
            raise TypeError("legacy dataset assembly requires artifact dictionaries")
        comparison = _comparison_for(target, artifacts)
        records = comparison["payload"].get("display_records")
        if not isinstance(records, list) or not records:
            raise ChartError("DAT-005", f"comparison {comparison['artifact_id']} has no display records", "data")
        source = comparison
    else:
        if not isinstance(artifacts, list):
            raise TypeError("legacy dataset assembly requires artifact dictionaries")
        source = _metric_for(target, artifacts)
        records = source["payload"]["records"]
    metadata_source = source if isinstance(target, ResolvedChartContext) else source["payload"]
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fields = sorted({field for record in records for field in record})
    return {
        "schema": [{"name": field, "role": "metric" if isinstance(next((r.get(field) for r in records if r.get(field) is not None), None), (int, float)) else "dimension"} for field in fields],
        "records": records,
        "row_count": len(records),
        "dataset_hash": f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}",
        "mode": "inline",
        "presentation_transforms": [],
        "null_handling": "preserve",
        "omitted_count": 0,
        "unit": metadata_source.get("unit"),
        "grain": metadata_source.get("grain"),
        **{key: metadata_source[key] for key in ("histogram_mode", "map_mode", "treemap_path") if key in metadata_source},
        **{key: metadata_source[key] for key in ("peer_definition", "peer_population", "peer_breakdown", "comparison_metric", "target_value", "peer_aggregate", "gap") if key in metadata_source},
    }
