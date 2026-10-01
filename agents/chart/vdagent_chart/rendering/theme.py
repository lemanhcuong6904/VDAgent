from __future__ import annotations

from typing import Any


DEFAULT_THEME: dict[str, Any] = {
    "font_family": "Inter, system-ui, sans-serif",
    "font_size": 12,
    "title_size": 18,
    "title_color": "#0f172a",
    "axis_color": "#334155",
    "primary_color": "#2563eb",
    "primary_dark": "#1d4ed8",
    "secondary_color": "#64748b",
    "success_color": "#14b8a6",
    "accent_color": "#f97316",
    "palette": ["#2563eb", "#14b8a6", "#f97316", "#8b5cf6", "#06b6d4", "#f43f5e", "#84cc16"],
    "background": "#ffffff",
    "grid_color": "#e2e8f0",
    "axis_line_color": "#cbd5e1",
    "paper_bgcolor": "#ffffff",
    "plot_bgcolor": "#ffffff",
}


def resolve_theme(_theme_ref: str | None) -> dict[str, Any]:
    return dict(DEFAULT_THEME)
