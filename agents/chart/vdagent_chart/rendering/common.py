from __future__ import annotations

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
    "stage": "Stage",
    "target": "Target",
    "value": "Value",
}


def text(value: Any, fallback: str = "") -> str:
    if isinstance(value, Mapping):
        return str(value.get("value") or fallback)
    return str(value or fallback)


def field(encoding: Mapping[str, Any], channel: str, fallback: str) -> str:
    value = encoding.get(channel)
    if isinstance(value, Mapping) and isinstance(value.get("field"), str):
        return str(value["field"])
    return fallback


def axis_title(presentation: Mapping[str, Any], axis: str, fallback: str) -> str:
    spec = presentation.get(f"{axis}_axis")
    if isinstance(spec, Mapping):
        return text(spec.get("title"), fallback)
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
        "title": {"text": title, "font": {"size": theme["title_size"]}},
        "font": {"family": theme["font_family"], "size": theme["font_size"]},
        "paper_bgcolor": theme["paper_bgcolor"],
        "plot_bgcolor": theme["plot_bgcolor"],
        "margin": {"l": 64, "r": 24, "t": 56, "b": 56},
        "hovermode": "closest",
    }


def cartesian_layout(spec: Mapping[str, Any], x_field: str, y_field: str) -> dict[str, Any]:
    spec_presentation = presentation(spec)
    rendered = layout(spec)
    rendered["xaxis"] = {"title": {"text": axis_title(spec_presentation, "x", x_field)}}
    rendered["yaxis"] = {"title": {"text": axis_title(spec_presentation, "y", y_field)}, "gridcolor": "#e5e7eb"}
    return rendered


def figure(data: list[dict[str, Any]], rendered_layout: dict[str, Any]) -> dict[str, Any]:
    return {
        "renderer": "plotly",
        "data": data,
        "layout": rendered_layout,
        "config": {"responsive": True, "displaylogo": False, "typesetMath": True},
    }
