from __future__ import annotations

from dataclasses import replace

from vdagent_chart.chart_plan import (
    chart_suggestion_from_plan,
    effective_visual_target,
    validate_encoding_plan,
    validate_presentation_plan,
)
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.policy import load_policy


def test_llm_plan_can_reclassify_visual_question_with_guarded_vocabulary() -> None:
    target = load_demo_task("bar").visual_targets[0]
    plan = {"visual_question": {"type": "actual_vs_target", "reason": "actual and target are present"}}

    effective = effective_visual_target(target, plan)

    assert effective.visual_question == "actual_vs_target"
    assert effective.target_id == target.target_id


def test_llm_plan_selection_uses_candidates_but_rejects_disallowed_chart_types() -> None:
    policy = load_policy("chart-policy/demo-1.0")
    plan = {
        "candidates": [
            {"chart_type": "made_up_chart", "reason": "invalid"},
            {"chart_type": "bullet", "reason": "compares actual against target"},
        ],
        "selection": {"chart_type": "bullet", "reason_codes": ["LLM_SEMANTIC_MATCH"]},
    }

    suggestion = chart_suggestion_from_plan(plan, policy.allowed_chart_types)

    assert suggestion["selected_chart_type"] == "bullet"
    assert suggestion["candidates"] == [{"chart_type": "bullet", "reason": "compares actual against target"}]


def test_llm_plan_encoding_is_field_guarded_but_presentation_is_preserved() -> None:
    dataset = {
        "schema": [
            {"name": "area_m2", "role": "metric"},
            {"name": "price_m2", "role": "metric"},
        ]
    }
    plan = {
        "encoding": {
            "x": {"field": "area_m2", "type": "quantitative"},
            "y": {"field": "invented_field", "type": "quantitative"},
        },
        "presentation": {
            "title": "Giá theo diện tích",
            "subtitle": "Không tính lại dữ liệu",
            "axes": {
                "x": {"title": {"format": "math", "value": "$S\\;(m^2)$"}},
                "y": {"title": {"format": "math", "value": "$P\\;(\\mathrm{million\\ VND}/m^2)$"}},
            },
        },
    }

    assert validate_encoding_plan(plan, dataset) == {"x": {"field": "area_m2", "type": "quantitative"}}
    presentation = validate_presentation_plan(plan, "Fallback", "Snapshot")
    assert presentation["title"] == "Giá theo diện tích"
    assert presentation["x_axis"]["title"]["value"] == "$S\\;(m^2)$"


def test_llm_presentation_rejects_malformed_axis_shapes_without_crashing() -> None:
    plan = {
        "presentation": {
            "title": "Inventory mix by bedroom type",
            "subtitle": "Share of synthetic units by bedroom type.",
            "axes": {
                "x": "Bedroom type",
                "y": ["Unit count"],
            },
        }
    }

    presentation = validate_presentation_plan(plan, "Fallback", "Snapshot")

    assert presentation["title"] == "Inventory mix by bedroom type"
    assert "x_axis" not in presentation
    assert "y_axis" not in presentation
