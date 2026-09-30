from __future__ import annotations

from typing import Any


DEFAULT_THEME: dict[str, Any] = {
    "font_family": "Inter, system-ui, sans-serif",
    "font_size": 12,
    "title_size": 17,
    "primary_color": "#2563eb",
    "secondary_color": "#64748b",
    "accent_color": "#f97316",
    "background": "#ffffff",
    "grid_color": "#e5e7eb",
    "paper_bgcolor": "#ffffff",
    "plot_bgcolor": "#ffffff",
}


def resolve_theme(_theme_ref: str | None) -> dict[str, Any]:
    return dict(DEFAULT_THEME)
