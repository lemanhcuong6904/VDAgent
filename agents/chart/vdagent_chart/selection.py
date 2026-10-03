from __future__ import annotations

from typing import Any

from .contracts import ChartPolicy, VisualTarget
from .compatibility import compatibility_errors
from .profile import DataProfile

QUESTION_ALIASES = {
    "trend": "trend_over_time",
    "comparison": "compare_categories",
    "composition": "composition_snapshot",
    "matrix": "matrix_intensity",
    "funnel": "funnel_conversion",
    "additive_change": "contribution_bridge",
    "hierarchy": "hierarchical_composition",
}

QUESTION_DEFAULTS = {
    "current_value": "kpi_card", "trend_over_time": "line", "cumulative_over_time": "area",
    "compare_categories": "bar", "compare_multiple_series": "grouped_bar", "target_vs_peer": "bar",
    "composition_snapshot": "pie", "composition_across_groups": "stacked_bar", "distribution": "histogram",
    "distribution_comparison": "box_plot", "relationship": "scatter", "matrix_intensity": "heatmap",
    "geospatial": "map", "funnel_conversion": "funnel", "contribution_bridge": "waterfall",
    "hierarchical_composition": "treemap", "actual_vs_target": "bullet",
}

QUESTION_COMPATIBLE_TYPES = {
    "current_value": ("kpi_card", "bullet"),
    "trend_over_time": ("line",),
    "cumulative_over_time": ("area",),
    "compare_categories": ("bar",),
    "compare_multiple_series": ("grouped_bar",),
    "target_vs_peer": ("bar", "bullet"),
    "composition_snapshot": ("pie",),
    "composition_across_groups": ("stacked_bar",),
    "distribution": ("histogram", "box_plot"),
    "distribution_comparison": ("box_plot",),
    "relationship": ("scatter",),
    "matrix_intensity": ("heatmap",),
    "geospatial": ("map",),
    "funnel_conversion": ("funnel",),
    "contribution_bridge": ("waterfall",),
    "hierarchical_composition": ("treemap",),
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
    question = QUESTION_ALIASES.get(target.visual_question, target.visual_question)
    preferred = llm_chart_type or target.preferred_chart_type
    expected = QUESTION_DEFAULTS.get(question, policy.fallback_chart_type)
    compatible = QUESTION_COMPATIBLE_TYPES.get(question, (expected,))
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
