from __future__ import annotations

from typing import Any

from .contracts import ChartPolicy, VisualTarget
from .compatibility import compatibility_errors
from .profile import DataProfile

QUESTION_DEFAULTS = {
    "current_value": "kpi_card", "trend": "line", "comparison": "bar", "target_vs_peer": "bar",
    "composition": "pie", "distribution": "histogram", "distribution_comparison": "box_plot",
    "relationship": "scatter", "matrix": "heatmap", "geospatial": "map", "funnel": "funnel",
    "additive_change": "waterfall", "hierarchy": "treemap", "actual_vs_target": "bullet",
}

QUESTION_COMPATIBLE_TYPES = {
    "current_value": ("kpi_card", "bullet"),
    "trend": ("line", "area"),
    "comparison": ("bar", "grouped_bar"),
    "target_vs_peer": ("bar", "bullet"),
    "composition": ("pie", "stacked_bar", "treemap"),
    "distribution": ("histogram", "box_plot"),
    "distribution_comparison": ("box_plot",),
    "relationship": ("scatter",),
    "matrix": ("heatmap",),
    "geospatial": ("map",),
    "funnel": ("funnel",),
    "additive_change": ("waterfall",),
    "hierarchy": ("treemap",),
    "actual_vs_target": ("bullet",),
}


def select_chart(
    target: VisualTarget,
    policy: ChartPolicy,
    llm_suggestion: str | dict[str, Any] | None = None,
    profile: DataProfile | None = None,
) -> dict[str, str | None]:
    llm_chart_type = (
        llm_suggestion.get("selected_chart_type")
        if isinstance(llm_suggestion, dict)
        else llm_suggestion
    )
    preferred = llm_chart_type or target.preferred_chart_type
    expected = QUESTION_DEFAULTS.get(target.visual_question, policy.fallback_chart_type)
    compatible = QUESTION_COMPATIBLE_TYPES.get(target.visual_question, (expected,))
    if preferred in compatible and preferred in policy.allowed_chart_types:
        selected = preferred
        reason = "SEL_LLM_ACCEPTED" if llm_chart_type == preferred else "SEL_PREFERENCE_ACCEPTED"
    else:
        selected, reason = expected if expected in policy.allowed_chart_types else policy.fallback_chart_type, "SEL_POLICY_VISUAL_QUESTION"
    errors = compatibility_errors(selected, profile) if profile is not None else ()
    if errors:
        return {"chart_type": policy.fallback_chart_type, "reason_code": "SEL_FALLBACK_INCOMPATIBLE", "fallback_reason": errors[0].code}
    decision: dict[str, Any] = {"chart_type": selected, "reason_code": reason, "fallback_reason": None}
    if isinstance(llm_suggestion, dict):
        decision["llm_candidates"] = list(llm_suggestion.get("candidates") or ())
    return decision
