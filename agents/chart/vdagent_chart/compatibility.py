"""Deterministic data-shape checks before a chart type may be selected."""

from __future__ import annotations

from .errors import ChartError
from .profile import DataProfile


def compatibility_errors(chart_type: str, profile: DataProfile) -> tuple[ChartError, ...]:
    errors: list[ChartError] = []
    if profile.row_count == 0:
        return (ChartError("DAT-002", f"{chart_type} requires at least one record", "data"),)
    if chart_type in {"line", "area"} and (not profile.has_time or profile.row_count < 2):
        errors.append(ChartError("DAT-002", f"{chart_type} requires an ordered time series with at least two records", "data"))
    if chart_type == "scatter" and len(profile.metric_fields) < 2:
        errors.append(ChartError("DAT-008", "scatter requires two numeric metrics", "data"))
    if chart_type in {"grouped_bar", "stacked_bar", "box_plot"} and len(profile.dimension_fields) < 2:
        errors.append(ChartError("DAT-009", f"{chart_type} requires a category and series/group dimension", "data"))
    if chart_type in {"pie", "treemap", "waterfall", "bullet", "kpi_card"} and not profile.metric_fields:
        errors.append(ChartError("DAT-010", f"{chart_type} requires at least one metric field", "data"))
    if chart_type == "heatmap" and (len(profile.dimension_fields) < 2 or not profile.metric_fields):
        errors.append(ChartError("DAT-011", "heatmap requires two dimensions and one metric", "data"))
    if chart_type == "map" and not {"lat", "lon"}.issubset(set(profile.metric_fields)):
        errors.append(ChartError("DAT-012", "map requires lat/lon point coordinates", "data"))
    return tuple(errors)
