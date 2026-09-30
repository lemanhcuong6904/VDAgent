"""Data-shape facts used by deterministic chart compatibility selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import EvidenceBinding, ResolvedChartContext


@dataclass(frozen=True)
class DataProfile:
    row_count: int
    metric_fields: tuple[str, ...]
    dimension_fields: tuple[str, ...]
    has_time: bool
    grain: str | None
    unit: str | None


def _records(
    context: ResolvedChartContext, binding: EvidenceBinding
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    artifacts = {artifact.artifact_id: artifact for artifact in context.artifacts}
    target = next(
        item
        for item in context.task.visual_targets
        if item.target_id == binding.target_id
    )
    if target.visual_question == "target_vs_peer" and binding.comparison_ids:
        source = artifacts[binding.comparison_ids[0]].payload
        return list(source["display_records"]), source
    source = artifacts[binding.metric_ids[0]].payload
    return list(source["records"]), source


def profile_target(
    context: ResolvedChartContext, binding: EvidenceBinding
) -> DataProfile:
    records, source = _records(context, binding)
    fields = {key for record in records for key in record}
    metrics = tuple(
        sorted(
            field
            for field in fields
            if any(isinstance(record.get(field), (int, float)) for record in records)
        )
    )
    dimensions = tuple(sorted(fields - set(metrics)))
    return DataProfile(
        len(records),
        metrics,
        dimensions,
        "month" in fields,
        source.get("grain"),
        source.get("unit"),
    )
