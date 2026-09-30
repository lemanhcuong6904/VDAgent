from __future__ import annotations

import re
from typing import Any, Mapping

from .theme import resolve_theme

FIELD_LABELS = {
    "actual": "Actual",
    "area": "Area",
    "area_m2": "$S\\;(m^2)$",
    "available": "Available units",
    "bin_start": "DOM bucket",
    "count": "Count",
    "dom": "DOM (days)",
    "inventory": "Inventory",
    "label": "Label",
    "lat": "Latitude",
    "lon": "Longitude",
    "month": "Month",
    "price_m2": "$P\\;(\\mathrm{million\\ VND}/m^2)$",
    "net_asking_price_per_m2": "$P_{net}/m^2$",
    "stage": "Stage",
    "target": "Target",
    "value": "Value",
}

_MATH_WRAPPED = re.compile(r"^\$(.*)\$$", re.DOTALL)
_PROSE_WORD = re.compile(r"[^\W\d_]{2,}\s+[^\W\d_]{2,}", re.UNICODE)


def text(value: Any, fallback: str = "") -> str:
    if isinstance(value, Mapping):
        return str(value.get("value") or fallback)
    return str(value or fallback)


def _plain_unit_text(value: str) -> str:
    return value.replace("m^2", "m²").replace("m2", "m²")


def _safe_title_text(value: Any, fallback: str = "") -> str:
    if not isinstance(value, Mapping):
        return _plain_unit_text(str(value or fallback))
    raw = str(value.get("value") or fallback)
    if value.get("format") != "math":
        return _plain_unit_text(raw)
    match = _MATH_WRAPPED.match(raw.strip())
    inner = match.group(1) if match else raw
    if _PROSE_WORD.search(inner) and "\\mathrm" not in inner:
        return _plain_unit_text(inner)
    return raw


def field(encoding: Mapping[str, Any], channel: str, fallback: str) -> str:
    value = encoding.get(channel)
    if isinstance(value, Mapping) and isinstance(value.get("field"), str):
        return str(value["field"])
    return fallback


def axis_title(presentation: Mapping[str, Any], axis: str, fallback: str) -> str:
    spec = presentation.get(f"{axis}_axis")
    if isinstance(spec, Mapping):
        return _safe_title_text(spec.get("title"), fallback)
    return FIELD_LABELS.get(fallback, fallback)


def records(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    dataset = spec.get("dataset", {})
    if not isinstance(dataset, Mapping):
        return []
    return [dict(record) for record in dataset.get("records", ()) if isinstance(record, Mapping)]


def encoding(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    value = spec.get("encoding", {})
    return value if isinstance(value, Mapping) else {}


def presentation(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    value = spec.get("presentation", {})
    return value if isinstance(value, Mapping) else {}


def layout(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_presentation = presentation(spec)
    theme = resolve_theme(str(spec_presentation.get("theme_ref") or "dashboard/default"))
    title = text(spec_presentation.get("title_spec"), str(spec_presentation.get("title", "")))
    return {
        "template": "plotly_white",
        "title": {
            "text": title,
            "x": 0.02,
            "xanchor": "left",
            "y": 0.97,
            "font": {"size": theme["title_size"], "color": theme["title_color"]},
        },
        "font": {"family": theme["font_family"], "size": theme["font_size"], "color": theme["axis_color"]},
        "colorway": list(theme["palette"]),
        "paper_bgcolor": theme["paper_bgcolor"],
        "plot_bgcolor": theme["plot_bgcolor"],
        "margin": {"l": 72, "r": 28, "t": 72, "b": 64},
        "hovermode": "closest",
        "hoverlabel": {"bgcolor": "#ffffff", "bordercolor": theme["axis_line_color"], "font": {"color": "#0f172a"}},
        "legend": {"orientation": "h", "x": 0, "y": -0.18, "xanchor": "left", "yanchor": "top"},
        "uniformtext": {"mode": "hide", "minsize": 10},
        "separators": ",.",
    }


def cartesian_layout(spec: Mapping[str, Any], x_field: str, y_field: str) -> dict[str, Any]:
    spec_presentation = presentation(spec)
    theme = resolve_theme(str(spec_presentation.get("theme_ref") or "dashboard/default"))
    rendered = layout(spec)
    rendered["xaxis"] = {
        "title": {"text": axis_title(spec_presentation, "x", x_field), "standoff": 12},
        "showgrid": False,
        "showline": True,
        "linecolor": theme["axis_line_color"],
        "ticks": "outside",
        "tickcolor": theme["axis_line_color"],
        "automargin": True,
    }
    rendered["yaxis"] = {
        "title": {"text": axis_title(spec_presentation, "y", y_field), "standoff": 14},
        "gridcolor": theme["grid_color"],
        "showgrid": True,
        "zeroline": False,
        "showline": False,
        "ticks": "outside",
        "tickcolor": theme["axis_line_color"],
        "automargin": True,
    }
    return rendered


def figure(data: list[dict[str, Any]], rendered_layout: dict[str, Any]) -> dict[str, Any]:
    return {
        "renderer": "plotly",
        "data": data,
        "layout": rendered_layout,
        "config": {"responsive": True, "displaylogo": False, "typesetMath": True},
    }
