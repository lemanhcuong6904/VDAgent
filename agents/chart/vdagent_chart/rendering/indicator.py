from __future__ import annotations

from typing import Any, Mapping

from .common import encoding, field, figure, layout, records


def render_kpi_card(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    first = records(spec)[0]
    value_field = field(spec_encoding, "value", "value")
    reference_field = field(spec_encoding, "reference", "reference")
    trace: dict[str, Any] = {"type": "indicator", "mode": "number", "value": first.get(value_field)}
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
