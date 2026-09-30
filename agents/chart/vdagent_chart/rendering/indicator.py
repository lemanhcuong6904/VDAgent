from __future__ import annotations

from typing import Any, Mapping

from .common import encoding, field, figure, layout, records


def _dataset_unit(spec: Mapping[str, Any]) -> str:
    dataset = spec.get("dataset", {})
    if not isinstance(dataset, Mapping):
        return ""
    return str(dataset.get("unit") or "").upper()


def _unit_suffix(unit: str) -> str:
    return {
        "DAY": " ngày",
        "DAYS": " ngày",
        "PCT": "%",
        "PERCENT": "%",
        "%": "%",
        "VND": " VND",
        "VND_PER_M2": " VND/m²",
    }.get(unit, "")


def render_kpi_card(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    first = records(spec)[0]
    value_field = field(spec_encoding, "value", "value")
    reference_field = field(spec_encoding, "reference", "reference")
    trace: dict[str, Any] = {
        "type": "indicator",
        "mode": "number",
        "value": first.get(value_field),
        "number": {"suffix": _unit_suffix(_dataset_unit(spec))},
    }
    if first.get("label"):
        trace["title"] = {"text": str(first["label"])}
    if reference_field in first:
        trace["mode"] = "number+delta"
        trace["delta"] = {"reference": first.get(reference_field)}
    return figure([trace], layout(spec))


def render_bullet(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    first = records(spec)[0]
    value_field = field(spec_encoding, "value", "actual")
    target_field = field(spec_encoding, "target", "target")
    return figure(
        [
            {
                "type": "indicator",
                "mode": "number+gauge",
                "value": first.get(value_field),
                "gauge": {"shape": "bullet", "threshold": {"value": first.get(target_field)}},
            }
        ],
        layout(spec),
    )
