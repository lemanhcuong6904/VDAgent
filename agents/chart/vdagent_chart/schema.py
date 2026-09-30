"""Strict schema boundary for demo task and pinned artifact JSON."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from .contracts import (
    ArtifactRef,
    ChartTaskInput,
    Intent,
    NormalizedArtifact,
    Scope,
    VisualTarget,
)
from .errors import ChartError

_TASK_FIELDS = frozenset(
    {
        "name",
        "schema_version",
        "run_id",
        "task_id",
        "mode",
        "scope",
        "intent",
        "visual_targets",
        "artifact_refs",
        "policy_ref",
        "idempotency_key",
        "requested_by",
        "auth_context",
        "trace_context",
    }
)
_MODES = frozenset(
    {"investigation_evidence", "direct_visualization", "report_compilation"}
)
_TYPES = frozenset({"metric", "evidence", "insight", "comparison"})


def _error(code: str, message: str) -> ChartError:
    return ChartError(code, message, "input")


def _scope(raw: object) -> Scope:
    if not isinstance(raw, Mapping):
        raise _error("INP-001", "scope must be an object")
    snapshot = raw.get("snapshot_id")
    if not isinstance(snapshot, str) or not snapshot:
        raise _error("INP-002", "scope.snapshot_id is required")
    time_range = raw.get("time_range")
    parsed_time: tuple[str, str] | None = None
    if time_range is not None:
        if (
            not isinstance(time_range, list)
            or len(time_range) != 2
            or not all(isinstance(v, str) for v in time_range)
        ):
            raise _error("INP-003", "scope.time_range must contain two ISO dates")
        try:
            start, end = date.fromisoformat(time_range[0]), date.fromisoformat(
                time_range[1]
            )
        except ValueError as exc:
            raise _error(
                "INP-003", "scope.time_range must contain two ISO dates"
            ) from exc
        if start > end:
            raise _error("INP-003", "scope.time_range start must not exceed end")
        parsed_time = (time_range[0], time_range[1])
    filters = raw.get("filters", [])
    if not isinstance(filters, list):
        raise _error("INP-004", "scope.filters must be a list")
    parsed_filters: list[tuple[str, str, str]] = []
    for item in filters:
        if not isinstance(item, Mapping) or not all(
            isinstance(item.get(k), str) for k in ("field", "operator", "value")
        ):
            raise _error(
                "INP-004", "each scope filter requires field, operator, and value"
            )
        parsed_filters.append((item["field"], item["operator"], item["value"]))
    return Scope(
        tuple(raw.get("project_ids", [])),
        tuple(raw.get("area_ids", [])),
        snapshot,
        parsed_time,
        raw.get("data_grain"),
        tuple(parsed_filters),
        raw.get("population_ref"),
    )


def parse_chart_task(raw: Mapping[str, Any]) -> ChartTaskInput:
    unknown = set(raw) - _TASK_FIELDS
    if unknown:
        raise _error("INP-001", f"unknown task fields: {sorted(unknown)}")
    required = (
        "schema_version",
        "run_id",
        "task_id",
        "mode",
        "scope",
        "visual_targets",
        "artifact_refs",
        "policy_ref",
        "idempotency_key",
    )
    if any(not raw.get(key) for key in required):
        raise _error("INP-001", "task is missing required fields")
    if raw["schema_version"] != "chart-task/2.0":
        raise _error("INP-001", "unsupported task schema")
    if raw["mode"] not in _MODES:
        raise _error("INP-005", "unsupported mode")
    intent_raw = raw.get("intent", {})
    if not isinstance(intent_raw, Mapping):
        raise _error("INP-006", "intent must be an object")
    purpose = intent_raw.get("purpose", raw["mode"])
    if not isinstance(purpose, str):
        raise _error("INP-006", "intent.purpose must be a string")
    targets = raw["visual_targets"]
    if not isinstance(targets, list) or not targets:
        raise _error("INP-007", "visual_targets must be a non-empty list")
    parsed_targets = tuple(
        VisualTarget(
            item["target_id"],
            item["visual_question"],
            item.get("purpose", purpose),
            item.get("preferred_chart_type"),
            tuple(item.get("artifact_ids", [])),
        )
        for item in targets
        if isinstance(item, Mapping)
        and isinstance(item.get("target_id"), str)
        and isinstance(item.get("visual_question"), str)
    )
    if len(parsed_targets) != len(targets):
        raise _error(
            "INP-007", "each visual target requires target_id and visual_question"
        )
    refs = raw["artifact_refs"]
    if not isinstance(refs, list) or not refs:
        raise _error("INP-008", "artifact_refs must be a non-empty list")
    parsed_refs: list[ArtifactRef] = []
    for ref in refs:
        if not isinstance(ref, Mapping) or not isinstance(ref.get("artifact_id"), str):
            raise _error("INP-008", "artifact reference requires artifact_id")
        if not isinstance(ref.get("version"), int) or isinstance(ref["version"], bool):
            raise _error("INP-008", "artifact reference requires an integer version")
        parsed_refs.append(
            ArtifactRef(
                ref["artifact_id"],
                ref["version"],
                ref.get("expected_hash"),
                ref.get("required", True),
            )
        )
    return ChartTaskInput(
        raw["schema_version"],
        raw["run_id"],
        raw["task_id"],
        raw["mode"],
        _scope(raw["scope"]),
        parsed_targets,
        tuple(parsed_refs),
        raw["policy_ref"],
        raw["idempotency_key"],
        Intent(
            purpose,
            intent_raw.get("business_question"),
            dict(intent_raw.get("presentation_context", {})),
        ),
        raw.get("requested_by"),
        dict(raw.get("auth_context", {})),
        dict(raw.get("trace_context", {})),
    )


def normalize_artifact(raw: Mapping[str, Any]) -> NormalizedArtifact:
    required = (
        "artifact_id",
        "version",
        "artifact_type",
        "run_id",
        "status",
        "content_hash",
        "scope",
        "payload",
    )
    if any(key not in raw for key in required):
        raise _error("INP-009", "artifact is missing required envelope fields")
    if raw["artifact_type"] not in _TYPES:
        raise _error("INP-009", "unsupported artifact type")
    if not isinstance(raw["version"], int) or isinstance(raw["version"], bool):
        raise _error("INP-009", "artifact requires an integer version")
    if not isinstance(raw["payload"], Mapping):
        raise _error("INP-009", "artifact payload must be an object")
    return NormalizedArtifact(
        raw["artifact_id"],
        raw["version"],
        raw["artifact_type"],
        raw["run_id"],
        raw["status"],
        raw["content_hash"],
        _scope(raw["scope"]),
        dict(raw["payload"]),
        tuple(raw.get("limitations", [])),
    )
