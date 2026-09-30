from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import re

from .errors import ChartError
from .safety import sanitize_text

_HTML = re.compile(r"<[^>]*>")
_CAUSAL = re.compile(
    r"\b(causes?|caused|because|therefore|dẫn đến|nguyên nhân)\b", re.IGNORECASE
)


def build_presentation(
    title: str,
    subtitle: str | None = None,
    annotations: list[dict[str, Any]] | None = None,
    axes: dict[str, dict[str, Any]] | None = None,
    legend: dict[str, Any] | None = None,
    theme_ref: str = "dashboard/default",
) -> dict[str, Any]:
    if _CAUSAL.search(title) or (subtitle and _CAUSAL.search(subtitle)):
        raise ChartError(
            "SEM-001",
            "causal wording is not allowed without causal evidence",
            "semantic",
        )
    clean_title = sanitize_text(_HTML.sub("", title))
    if not clean_title:
        raise ChartError("SEM-002", "chart title must not be empty", "semantic")
    presentation: dict[str, Any] = {
        "title": clean_title,
        "title_spec": {"format": "plain", "value": clean_title},
        "subtitle": sanitize_text(_HTML.sub("", subtitle or "")),
        "subtitle_spec": {"format": "plain", "value": sanitize_text(_HTML.sub("", subtitle or ""))},
        "language": "vi-VN",
        "theme_ref": theme_ref,
    }
    if axes:
        if isinstance(axes.get("x"), Mapping):
            presentation["x_axis"] = dict(axes["x"])
        if isinstance(axes.get("y"), Mapping):
            presentation["y_axis"] = dict(axes["y"])
    if annotations:
        presentation["annotations"] = [
            {
                key: sanitize_text(_HTML.sub("", str(value))) if isinstance(value, str) else value
                for key, value in annotation.items()
            }
            for annotation in annotations
            if isinstance(annotation, dict)
        ]
    if legend:
        clean_legend: dict[str, Any] = {}
        if legend.get("title"):
            clean_legend["title"] = sanitize_text(_HTML.sub("", str(legend["title"])))
        items = legend.get("items")
        if isinstance(items, Mapping):
            clean_legend["items"] = {
                str(key): sanitize_text(_HTML.sub("", str(value)))
                for key, value in items.items()
                if str(value).strip()
            }
        if clean_legend:
            presentation["legend"] = clean_legend
    return presentation
