from __future__ import annotations

from typing import Any, Mapping

from .common import encoding, field, figure, layout, records


def render_pie(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    label_field = field(spec_encoding, "color", "label")
    value_field = field(spec_encoding, "theta", "value")
    return figure(
        [
            {
                "type": "pie",
                "labels": [record.get(label_field) for record in spec_records],
                "values": [record.get(value_field) for record in spec_records],
                "hole": 0.35,
                "textinfo": "label+percent",
            }
        ],
        layout(spec),
    )
