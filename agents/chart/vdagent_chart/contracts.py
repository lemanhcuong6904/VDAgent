from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ArtifactType = Literal["metric", "evidence", "insight", "comparison"]


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    version: int
    expected_hash: str | None = None
    required: bool = True


@dataclass(frozen=True)
class Scope:
    project_ids: tuple[str, ...] = ()
    area_ids: tuple[str, ...] = ()
    snapshot_id: str | None = None
    time_range: tuple[str, str] | None = None
    data_grain: str | None = None
    filters: tuple[tuple[str, str, str], ...] = ()
    population_ref: str | None = None


@dataclass(frozen=True)
class Intent:
    purpose: str = "direct_visualization"
    business_question: str | None = None
    presentation_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualTarget:
    target_id: str
    visual_question: str
    purpose: str = "direct_visualization"
    preferred_chart_type: str | None = None
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChartTaskInput:
    schema_version: str
    run_id: str
    task_id: str
    mode: str
    scope: Scope
    visual_targets: tuple[VisualTarget, ...]
    artifact_refs: tuple[ArtifactRef, ...]
    policy_ref: str
    idempotency_key: str
    intent: Intent = field(default_factory=Intent)
    requested_by: str | None = None
    auth_context: dict[str, Any] = field(default_factory=dict)
    trace_context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedArtifact:
    artifact_id: str
    version: int
    artifact_type: ArtifactType
    run_id: str
    status: str
    content_hash: str
    scope: Scope
    payload: dict[str, Any]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedChartContext:
    task: ChartTaskInput
    policy: ChartPolicy
    artifacts: tuple[NormalizedArtifact, ...]
    validation: dict[str, Any]


@dataclass(frozen=True)
class EvidenceBinding:
    target_id: str
    metric_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    insight_ids: tuple[str, ...] = ()
    comparison_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChartPolicy:
    ruleset_version: str
    allowed_chart_types: tuple[str, ...]
    max_categories: int
    max_series: int
    max_points: int
    allow_dual_axis: bool
    allow_imputation: bool
    allow_silent_truncation: bool
    fallback_chart_type: str = "table"


@dataclass(frozen=True)
class ChartSpecArtifact:
    artifact_id: str
    version: int
    status: str
    chart_type: str
    title: str
    render_spec: dict[str, Any]
    dataset: dict[str, Any]
    lineage: dict[str, Any]
    validation: dict[str, Any]
    content_hash: str
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetResult:
    target_id: str
    status: str
    chart_ref: str | None = None
    fallback: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class ChartTaskResult:
    schema_version: str
    run_id: str
    task_id: str
    status: str
    chart_artifacts: tuple[str, ...] = ()
    target_results: tuple[TargetResult, ...] = ()
    warnings: tuple[dict[str, Any], ...] = ()
    errors: tuple[dict[str, Any], ...] = ()
    dependency_requests: tuple[dict[str, Any], ...] = ()
