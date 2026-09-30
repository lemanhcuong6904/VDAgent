from __future__ import annotations

from typing import Any, Mapping

from .common import encoding, field, figure, layout, records


def render_funnel(spec: Mapping[str, Any]) -> dict[str, Any]:
    ordered = sorted(records(spec), key=lambda item: item.get("order", 0))
    return figure(
        [
            {
                "type": "funnel",
                "y": [record.get("stage") for record in ordered],
                "x": [record.get("count") for record in ordered],
                "textinfo": "value+percent initial",
                "hovertemplate": "stage: %{y}<br>count: %{x}<extra></extra>",
            }
        ],
        layout(spec),
    )


def render_waterfall(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    label_field = field(spec_encoding, "x", "label")
    value_field = field(spec_encoding, "y", "value")
    measure_field = field(spec_encoding, "measure", "measure")
    return figure(
        [
            {
                "type": "waterfall",
                "x": [record.get(label_field) for record in spec_records],
                "y": [record.get(value_field) for record in spec_records],
                "measure": [record.get(measure_field, "relative") for record in spec_records],
            }
        ],
        layout(spec),
    )
