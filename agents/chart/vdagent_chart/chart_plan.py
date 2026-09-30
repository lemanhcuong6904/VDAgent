from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .contracts import VisualTarget
from .presentation import build_presentation
from .selection import QUESTION_DEFAULTS

ENCODING_CHANNELS = (
    "x",
    "y",
    "theta",
    "color",
    "detail",
    "series",
    "value",
    "reference",
    "target",
    "lat",
    "lon",
    "measure",
)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def effective_visual_target(target: VisualTarget, plan: Mapping[str, object]) -> VisualTarget:
    raw = _mapping(plan.get("visual_question"))
    visual_question = raw.get("type") or plan.get("visual_question")
    if isinstance(visual_question, str) and visual_question in QUESTION_DEFAULTS:
        return replace(target, visual_question=visual_question)
    return target


def chart_suggestion_from_plan(plan: Mapping[str, object], allowed_chart_types: tuple[str, ...]) -> dict[str, object]:
    allowed = set(allowed_chart_types)
    raw_candidates = plan.get("candidates")
    candidates: list[dict[str, object]] = []
    if isinstance(raw_candidates, list):
        for item in raw_candidates:
            if isinstance(item, Mapping) and item.get("chart_type") in allowed:
                candidates.append({"chart_type": item["chart_type"], "reason": str(item.get("reason", ""))})
    selection = _mapping(plan.get("selection"))
    selected = selection.get("chart_type") or plan.get("selected_chart_type") or plan.get("chart_type")
    return {
        "selected_chart_type": selected if isinstance(selected, str) and selected in allowed else None,
        "candidates": candidates,
        "reason_codes": list(selection.get("reason_codes") or ()),
        "transform_intents": list(plan.get("transform_intents") or ()),
    }


def validate_encoding_plan(plan: Mapping[str, object], dataset: Mapping[str, object]) -> dict[str, object] | None:
    raw = _mapping(plan.get("encoding"))
    if not raw:
        return None
    fields = {
        item.get("name")
        for item in dataset.get("schema", ())
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    encoding: dict[str, object] = {}
    for channel in ENCODING_CHANNELS:
        value = raw.get(channel)
        if isinstance(value, Mapping) and value.get("field") in fields:
            encoding[channel] = dict(value)
    path = raw.get("path")
    if isinstance(path, list) and path and all(isinstance(item, str) and item in fields for item in path):
        encoding["path"] = list(path)
    sort = raw.get("sort")
    if isinstance(sort, Mapping) and sort.get("field") in fields and isinstance(encoding.get("x"), dict):
        order = "descending" if sort.get("order") == "descending" else "ascending"
        encoding["x"]["sort"] = {"field": str(sort["field"]), "order": order}
    return encoding or None


def validate_presentation_plan(
    plan: Mapping[str, object],
    default_title: str,
    default_subtitle: str,
) -> dict[str, object]:
    raw = _mapping(plan.get("presentation"))
    if not raw:
        return build_presentation(default_title, default_subtitle)
    axes = raw.get("axes")
    if isinstance(axes, Mapping):
        axes = {key: value for key, value in axes.items() if key in {"x", "y"} and isinstance(value, Mapping)}
    else:
        axes = {key[0]: raw[key] for key in ("x_axis", "y_axis") if isinstance(raw.get(key), Mapping)}
    title = str(raw.get("title") or default_title)
    subtitle = str(raw.get("subtitle") or default_subtitle)
    annotations = raw.get("annotations")
    return build_presentation(
        title,
        subtitle,
        annotations if isinstance(annotations, list) else None,
        axes=dict(axes) if axes else None,
        theme_ref=str(raw.get("theme_ref") or "dashboard/default"),
    )
