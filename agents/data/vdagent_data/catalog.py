"""The Data catalog, generated from the semantic layer (build spec 02 §3, DEC-036).

`vdagent_contracts/catalogs/data.json` is the frozen copy the Orchestrator reads; a test keeps it equal to
`build_catalog()`. Regenerate with `uv run python -m vdagent_data.catalog`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vdagent_contracts.catalog import AgentCatalog
from vdagent_data.semantic.loader import LAYER, Layer

CONTRACT_VERSION = "1.0.0"
DEADLINE_S = 90

ERROR_CODES: dict[str, str] = {
    "AMBIGUOUS_REQUEST": "NEED_INPUT",
    "ENTITY_NOT_FOUND": "SPEC_ISSUE",
    "SPEC_MISMATCH": "SPEC_ISSUE",
    "OUT_OF_SCOPE": "NO_ACCESS",
    "SIGNATURE_INVALID": "NO_ACCESS",  # kept for the contract; no path produces it here (DEC-019)
    "DATA_UNAVAILABLE": "NO_DATA",
    "DQ_BLOCKING": "DATA_QUALITY",
    "BUDGET_EXCEEDED": "SPEC_ISSUE",
    "LLM_UNAVAILABLE": "TRANSIENT",
    "LLM_QUOTA_EXHAUSTED": "QUOTA_EXHAUSTED",
    "INTERNAL_ERROR": "FATAL",
}

_MENTION = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "kind_hint": {"type": "string", "enum": ["PROJECT", "ZONE", "UNIT", "UNKNOWN"]},
    },
    "required": ["text", "kind_hint"],
    "additionalProperties": False,
}


def _names(values: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string", "enum": sorted(values)}}


def _common(layer: Layer) -> dict[str, Any]:
    return {
        "objective": {"type": "string", "maxLength": 300},
        "scope": {
            "type": "object",
            "properties": {"mentions": {"type": "array", "items": _MENTION}, "scope_all": {"type": "boolean"}},
            "required": ["mentions", "scope_all"],
            "additionalProperties": False,
        },
        "filters": _names(layer.filters),
        "extra_needs": {"type": "array", "items": {"type": "string", "maxLength": 300}},
        "acceptance": {
            "type": "object",
            "properties": {"grain": {"type": "string"}, "min_rows": {"type": "integer"}},
            "additionalProperties": False,
        },
    }


def _schema(layer: Layer, extra: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**_common(layer), **extra},
        "required": ["objective", "scope", *required],
        "additionalProperties": False,
    }


def build_catalog(layer: Layer = LAYER) -> AgentCatalog:
    common_op = {"deadline_s": DEADLINE_S, "error_codes": ERROR_CODES, "retries_transient_internally": True}
    metrics = {**_names(layer.metrics), "minItems": 1}
    return AgentCatalog.model_validate(
        {
            "agent": "data",
            "contract_version": CONTRACT_VERSION,
            "catalog_version": layer.semantic_version,
            "operations": [
                {
                    "operation": "fetch_units",
                    "description": "Lấy danh sách căn theo phạm vi và bộ lọc, kèm chẩn đoán và nguyên nhân (unit_set)",
                    "input_schema": _schema(layer, {"attributes": _names(layer.attributes)}, []),
                    "produces": ["unit_set", "dq_report"],
                    "outputs": ["CHAT_ANSWER"],
                    "serves": ["LOOKUP"],
                    **common_op,
                },
                {
                    "operation": "aggregate_metrics",
                    "description": "Tính metric theo nhóm (tử số, mẫu số, n, formula_id) trong phạm vi (metric_table)",
                    "input_schema": _schema(
                        layer, {"metrics": metrics, "group_by": _names(layer.dimensions)}, ["metrics"]
                    ),
                    "produces": ["metric_table", "dq_report"],
                    "outputs": ["CHAT_ANSWER"],
                    "serves": ["LOOKUP"],
                    **common_op,
                },
                {
                    "operation": "fetch_peer_candidates",
                    "description": "Lấy tập căn ứng viên tương đồng cho một căn mục tiêu (peer_candidates)",
                    "input_schema": _schema(layer, {"target_unit": _MENTION}, ["target_unit"]),
                    "produces": ["peer_candidates", "dq_report"],
                    **common_op,
                },
                {
                    "operation": "fetch_unit_context",
                    "description": "Lấy lịch sử giá, phễu, thứ cấp, vĩ mô, hạ tầng cho một tập căn (unit_context)",
                    "input_schema": _schema(
                        layer,
                        {
                            "unit_set_package_id": {"type": "string"},
                            "contexts": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["price_history", "funnel", "secondary_comps", "macro", "infrastructure"],
                                },
                            },
                        },
                        ["unit_set_package_id", "contexts"],
                    ),
                    "input_fields": {"unit_set": "unit_set_package_id"},
                    "requires": ["unit_set"],
                    "produces": ["unit_context", "dq_report"],
                    **common_op,
                },
            ],
            "vocabulary": {
                "metrics": [{"name": n, "description": m.description} for n, m in layer.metrics.items()],
                "dimensions": [{"name": n, "description": d.description} for n, d in layer.dimensions.items()],
                "filters": [{"name": n, "description": f.description} for n, f in layer.filters.items()],
                "attributes": [{"name": n, "description": a.description} for n, a in layer.attributes.items()],
            },
        }
    )


def write_frozen_copy(target: Path | None = None) -> Path:
    import vdagent_contracts.catalogs as catalogs

    path = target or Path(catalogs.__file__).resolve().parent / "data.json"
    path.write_text(
        json.dumps(build_catalog().model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


if __name__ == "__main__":
    print(write_frozen_copy())
