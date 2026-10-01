from __future__ import annotations

from typing import Any, Mapping

from .common import apply_legend, cartesian_layout, encoding, field, figure, legend_label, presentation, records
from .theme import resolve_theme


def _xy_trace(chart_type: str, spec: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
    theme = resolve_theme(None)
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    x_field = field(spec_encoding, "x", "label")
    y_field = field(spec_encoding, "y", "value")
    spec_presentation = presentation(spec)
    trace_type = "scatter" if chart_type in {"line", "area", "scatter"} else "bar"
    trace: dict[str, Any] = {
        "type": trace_type,
        "x": [record.get(x_field) for record in spec_records],
        "y": [record.get(y_field) for record in spec_records],
        "name": legend_label(spec_presentation, y_field, y_field),
        "hovertemplate": f"{x_field}: %{{x}}<br>{y_field}: %{{y}}<extra></extra>",
    }
    if trace_type == "bar":
        trace["marker"] = {
            "color": theme["primary_color"],
            "line": {"color": theme["primary_dark"], "width": 1},
        }
        trace["opacity"] = 0.92
    if chart_type == "line":
        trace["mode"] = "lines+markers"
        trace["line"] = {"color": theme["primary_color"], "width": 3, "shape": "spline"}
        trace["marker"] = {"color": theme["primary_color"], "size": 8, "line": {"color": "#ffffff", "width": 1.5}}
    elif chart_type == "area":
        trace["mode"] = "lines"
        trace["fill"] = "tozeroy"
        trace["line"] = {"color": theme["primary_color"], "width": 2.5, "shape": "spline"}
        trace["fillcolor"] = "rgba(37, 99, 235, 0.18)"
    elif chart_type == "scatter":
        trace["mode"] = "markers"
        trace["marker"] = {
            "color": theme["primary_color"],
            "size": 11,
            "opacity": 0.86,
            "line": {"color": "#ffffff", "width": 1.5},
        }
        detail = spec_encoding.get("detail")
        if isinstance(detail, Mapping) and isinstance(detail.get("field"), str):
            trace["text"] = [record.get(str(detail["field"])) for record in spec_records]
            trace["hovertemplate"] = f"{detail['field']}: %{{text}}<br>{x_field}: %{{x}}<br>{y_field}: %{{y}}<extra></extra>"
    return trace, x_field, y_field


def render_xy(chart_type: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    trace, x_field, y_field = _xy_trace(chart_type, spec)
    rendered_layout = cartesian_layout(spec, x_field, y_field)
    apply_legend(rendered_layout, presentation(spec), 1)
    if chart_type == "bar":
        rendered_layout["bargap"] = 0.32
    return figure([trace], rendered_layout)


def render_grouped_bar(spec: Mapping[str, Any]) -> dict[str, Any]:
    return _render_series_bar(spec, "group")


def render_stacked_bar(spec: Mapping[str, Any]) -> dict[str, Any]:
    return _render_series_bar(spec, "stack")


def _render_series_bar(spec: Mapping[str, Any], barmode: str) -> dict[str, Any]:
    theme = resolve_theme(None)
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    x_field = field(spec_encoding, "x", "label")
    y_field = field(spec_encoding, "y", "value")
    series_field = field(spec_encoding, "series", "series")
    spec_presentation = presentation(spec)
    series_values = list(dict.fromkeys(record.get(series_field) for record in spec_records))
    palette = list(theme["palette"])
    traces = [
        {
            "type": "bar",
            "name": legend_label(spec_presentation, series, str(series)),
            "x": [record.get(x_field) for record in spec_records if record.get(series_field) == series],
            "y": [record.get(y_field) for record in spec_records if record.get(series_field) == series],
            "marker": {
                "color": palette[index % len(palette)],
                "line": {"color": "rgba(15, 23, 42, 0.18)", "width": 1},
            },
            "opacity": 0.94,
        }
        for index, series in enumerate(series_values)
    ]
    rendered_layout = cartesian_layout(spec, x_field, y_field)
    rendered_layout["barmode"] = barmode
    rendered_layout["bargap"] = 0.28
    rendered_layout["bargroupgap"] = 0.08
    apply_legend(rendered_layout, spec_presentation, len(traces))
    return figure(traces, rendered_layout)
