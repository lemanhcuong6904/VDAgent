from __future__ import annotations

from typing import Any

from vdagent_contracts.vega_lite import VEGA_LITE_SCHEMA

from .spec_builder import build_encoding

VEGA_SCHEMA = VEGA_LITE_SCHEMA  # the major version the frontend bundles (vega-lite 6)


def build_vega_spec(chart_type: str, records: list[dict[str, Any]], title: str) -> dict[str, Any]:
    if chart_type == "funnel":
        return {
            "$schema": VEGA_SCHEMA,
            "title": title,
            "data": {"values": records},
            "transform": [
                {"joinaggregate": [{"op": "max", "field": "count", "as": "max_count"}]},
                {"calculate": "(datum.max_count - datum.count) / 2", "as": "center_offset"},
                {"calculate": "datum.center_offset + datum.count", "as": "funnel_end"},
            ],
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {
                "y": {
                    "field": "stage",
                    "type": "nominal",
                    "sort": {"field": "order", "order": "ascending"},
                    "title": "stage",
                },
                "x": {"field": "center_offset", "type": "quantitative", "axis": None},
                "x2": {"field": "funnel_end"},
                "color": {"field": "stage", "type": "nominal", "legend": None},
                "tooltip": [
                    {"field": "stage", "type": "nominal"},
                    {"field": "count", "type": "quantitative"},
                ],
            },
        }
    mark, encoding = project_encoding(chart_type, build_encoding(chart_type, records), records)
    return _sized({"$schema": VEGA_SCHEMA, "title": title, "data": {"values": records}, "mark": mark, "encoding": encoding})


def _sized(spec: dict[str, Any]) -> dict[str, Any]:
    """Text views get a fixed height (one 40px row per label): a discrete y in a container-sized view warns in the UI."""
    spec.pop("height", None)
    if spec["mark"].get("type") == "text":
        field = (spec["encoding"].get("y") or {}).get("field")
        rows = len({str(r.get(field)) for r in spec["data"]["values"]}) if field else 1
        spec["height"] = max(60, 40 * rows)
    return spec


def _field(definition: Any) -> str | None:
    return definition.get("field") if isinstance(definition, dict) else None


def _typed(field: str | None, kind: str, **extra: Any) -> dict[str, Any]:
    return {"field": field, "type": kind, **extra}


def project_encoding(chart_type: str, semantic: dict[str, Any], records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map the semantic encoding (chart vocabulary: label/value/reference/series/measure/path…) onto Vega-Lite marks
    and channels (WS7 F-01). Chart types Vega-Lite has no mark for (kpi_card, bullet, treemap, table, waterfall) get
    the closest faithful single-view projection; the semantic spec keeps the original chart type."""
    present = {k for record in records for k in record}
    enc = {k: v for k, v in semantic.items()}
    tooltip = [{"field": f} for f in sorted(present)]
    if chart_type in {"kpi_card", "bullet", "table"}:
        label = _field(enc.get("label")) or _field(enc.get("x")) or next(iter(sorted(present)), None)
        value = _field(enc.get("value")) or _field(enc.get("y"))
        encoding = {"text": _typed(value, "quantitative", format=",")}
        if label in present:
            encoding["y"] = _typed(label, "nominal", title=None)
        return {"type": "text", "fontSize": 24, "tooltip": True}, {**encoding, "tooltip": tooltip}
    if chart_type in {"grouped_bar", "stacked_bar"}:
        series = _field(enc.get("series"))
        encoding = {"x": enc["x"], "y": enc["y"], "color": _typed(series, "nominal")}
        if chart_type == "grouped_bar":
            encoding["xOffset"] = _typed(series, "nominal")
        return {"type": "bar", "tooltip": True}, encoding
    if chart_type == "waterfall":
        return {"type": "bar", "tooltip": True}, {"x": enc["x"], "y": enc["y"], "color": _typed(_field(enc.get("measure")), "nominal")}
    if chart_type == "treemap":
        path = [p for p in enc.get("path") or () if p in present]
        return {"type": "bar", "tooltip": True}, {"y": _typed(path[0] if path else None, "nominal"), "x": enc["value"],
                                                  **({"color": _typed(path[1], "nominal")} if len(path) > 1 else {})}
    if chart_type == "map":
        return {"type": "circle", "tooltip": True}, {"longitude": enc["lon"], "latitude": enc["lat"], "color": enc["color"]}
    if chart_type == "box_plot":
        return {"type": "boxplot"}, {"x": enc["x"], "y": enc["y"]}
    mark = {"pie": "arc", "heatmap": "rect", "scatter": "point", "histogram": "bar"}.get(chart_type, chart_type)
    return {"type": mark, "tooltip": True}, enc


def render_vega(spec: dict[str, Any]) -> dict[str, Any]:
    """Project an already validated semantic spec to a Vega-Lite document."""
    dataset = spec.get("dataset", {})
    presentation = spec.get("presentation", {})
    chart_type = str(spec["chart_type"])
    rendered = build_vega_spec(chart_type, list(dataset.get("records", ())), str(presentation.get("title", "")))
    if chart_type != "funnel" and spec.get("encoding"):
        rendered["mark"], rendered["encoding"] = project_encoding(chart_type, dict(spec["encoding"]), list(dataset.get("records", ())))
    return _sized(rendered)
