from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import ChartError
from .cartesian import render_grouped_bar, render_stacked_bar, render_xy
from .composition import render_pie
from .flow import render_funnel, render_waterfall
from .geospatial import render_map
from .hierarchy import render_treemap
from .indicator import render_bullet, render_kpi_card
from .statistical import render_box_plot, render_heatmap, render_histogram

Renderer = Callable[[dict[str, Any]], dict[str, Any]]

RENDERERS: dict[str, Renderer] = {
    "kpi_card": render_kpi_card,
    "line": lambda spec: render_xy("line", spec),
    "area": lambda spec: render_xy("area", spec),
    "bar": lambda spec: render_xy("bar", spec),
    "grouped_bar": render_grouped_bar,
    "stacked_bar": render_stacked_bar,
    "pie": render_pie,
    "scatter": lambda spec: render_xy("scatter", spec),
    "histogram": render_histogram,
    "box_plot": render_box_plot,
    "heatmap": render_heatmap,
    "map": render_map,
    "funnel": render_funnel,
    "waterfall": render_waterfall,
    "treemap": render_treemap,
    "bullet": render_bullet,
}


def render_plotly(spec: dict[str, Any]) -> dict[str, Any]:
    chart_type = str(spec.get("chart_type") or "")
    renderer = RENDERERS.get(chart_type)
    if renderer is None:
        raise ChartError("REN-001", f"unsupported chart type: {chart_type}", "renderer")
    return renderer(spec)
