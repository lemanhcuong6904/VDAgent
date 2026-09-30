from __future__ import annotations

from typing import Any, Mapping

from .common import cartesian_layout, encoding, field, figure, records


def _xy_trace(chart_type: str, spec: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    x_field = field(spec_encoding, "x", "label")
    y_field = field(spec_encoding, "y", "value")
    trace_type = "scatter" if chart_type in {"line", "area", "scatter"} else "bar"
    trace: dict[str, Any] = {
        "type": trace_type,
        "x": [record.get(x_field) for record in spec_records],
        "y": [record.get(y_field) for record in spec_records],
        "name": y_field,
        "hovertemplate": f"{x_field}: %{{x}}<br>{y_field}: %{{y}}<extra></extra>",
    }
    if chart_type == "line":
        trace["mode"] = "lines+markers"
    elif chart_type == "area":
        trace["mode"] = "lines"
        trace["fill"] = "tozeroy"
    elif chart_type == "scatter":
        trace["mode"] = "markers"
        detail = spec_encoding.get("detail")
        if isinstance(detail, Mapping) and isinstance(detail.get("field"), str):
            trace["text"] = [record.get(str(detail["field"])) for record in spec_records]
            trace["hovertemplate"] = f"{detail['field']}: %{{text}}<br>{x_field}: %{{x}}<br>{y_field}: %{{y}}<extra></extra>"
    return trace, x_field, y_field


def render_xy(chart_type: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    trace, x_field, y_field = _xy_trace(chart_type, spec)
    return figure([trace], cartesian_layout(spec, x_field, y_field))


def render_grouped_bar(spec: Mapping[str, Any]) -> dict[str, Any]:
    return _render_series_bar(spec, "group")


def render_stacked_bar(spec: Mapping[str, Any]) -> dict[str, Any]:
    return _render_series_bar(spec, "stack")


def _render_series_bar(spec: Mapping[str, Any], barmode: str) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    x_field = field(spec_encoding, "x", "label")
    y_field = field(spec_encoding, "y", "value")
    series_field = field(spec_encoding, "series", "series")
    series_values = list(dict.fromkeys(record.get(series_field) for record in spec_records))
    traces = [
        {
            "type": "bar",
            "name": str(series),
            "x": [record.get(x_field) for record in spec_records if record.get(series_field) == series],
            "y": [record.get(y_field) for record in spec_records if record.get(series_field) == series],
        }
        for series in series_values
    ]
    rendered_layout = cartesian_layout(spec, x_field, y_field)
    rendered_layout["barmode"] = barmode
    return figure(traces, rendered_layout)
