from __future__ import annotations

from typing import Any, Mapping

from .common import encoding, field, figure, layout, records


def render_map(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    lat_field = field(spec_encoding, "lat", "lat")
    lon_field = field(spec_encoding, "lon", "lon")
    color_field = field(spec_encoding, "color", "value")
    rendered_layout = layout(spec)
    rendered_layout["map"] = {"style": "open-street-map", "zoom": 10}
    return figure(
        [
            {
                "type": "scattermap",
                "lat": [record.get(lat_field) for record in spec_records],
                "lon": [record.get(lon_field) for record in spec_records],
                "mode": "markers",
                "marker": {"size": 12, "color": [record.get(color_field) for record in spec_records], "colorscale": "Blues"},
                "text": [record.get("label") for record in spec_records],
            }
        ],
        rendered_layout,
    )
