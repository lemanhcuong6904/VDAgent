from __future__ import annotations

from typing import Any, Mapping

from .common import FIELD_LABELS, cartesian_layout, encoding, field, figure, records


def render_histogram(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    if spec_records and {"bin_start", "bin_end", "count"}.issubset(spec_records[0]):
        trace = {
            "type": "bar",
            "x": [f"{record.get('bin_start')}–{record.get('bin_end')}" for record in spec_records],
            "y": [record.get("count") for record in spec_records],
            "name": "count",
            "hovertemplate": "bucket: %{x}<br>count: %{y}<extra></extra>",
        }
        rendered_layout = cartesian_layout(spec, "bin_start", "count")
        rendered_layout["bargap"] = 0.02
        return figure([trace], rendered_layout)
    x_field = field(spec_encoding, "x", "value")
    return figure([{"type": "histogram", "x": [record.get(x_field) for record in spec_records], "name": x_field}], cartesian_layout(spec, x_field, "count"))


def render_box_plot(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    x_field = field(spec_encoding, "x", "label")
    y_field = field(spec_encoding, "y", "value")
    return figure(
        [
            {
                "type": "box",
                "x": [record.get(x_field) for record in spec_records],
                "y": [record.get(y_field) for record in spec_records],
                "boxpoints": "outliers",
            }
        ],
        cartesian_layout(spec, x_field, y_field),
    )


def render_heatmap(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    x_field = field(spec_encoding, "x", "x")
    y_field = field(spec_encoding, "y", "y")
    color_field = field(spec_encoding, "color", "value")
    x_values = list(dict.fromkeys(record.get(x_field) for record in spec_records))
    y_values = list(dict.fromkeys(record.get(y_field) for record in spec_records))
    lookup = {(record.get(x_field), record.get(y_field)): record.get(color_field) for record in spec_records}
    return figure(
        [
            {
                "type": "heatmap",
                "x": x_values,
                "y": y_values,
                "z": [[lookup.get((x_value, y_value)) for x_value in x_values] for y_value in y_values],
                "colorscale": "Blues",
                "colorbar": {"title": {"text": FIELD_LABELS.get(color_field, color_field)}},
                "hovertemplate": (
                    f"{FIELD_LABELS.get(x_field, x_field)}: %{{x}}<br>"
                    f"{FIELD_LABELS.get(y_field, y_field)}: %{{y}}<br>"
                    f"{FIELD_LABELS.get(color_field, color_field)}: %{{z}}<extra></extra>"
                ),
            }
        ],
        cartesian_layout(spec, x_field, y_field),
    )
