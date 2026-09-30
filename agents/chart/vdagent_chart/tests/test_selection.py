from __future__ import annotations

import unittest

from vdagent_chart.contracts import VisualTarget
from vdagent_chart.policy import load_policy
from vdagent_chart.selection import select_chart
from vdagent_chart.profile import DataProfile


class SelectionTests(unittest.TestCase):
    def test_incompatible_preference_falls_back_to_a_table(self) -> None:
        profile = DataProfile(1, ("price_m2",), ("label",), False, "month", "VND/m2")
        policy = load_policy("chart-policy/demo-1.0")
        decision = select_chart(VisualTarget("target", "trend", preferred_chart_type="line"), policy, profile=profile)

        self.assertEqual(decision["chart_type"], "table")
        self.assertEqual(decision["fallback_reason"], "DAT-002")

    def test_maps_visual_questions_to_policy_compatible_chart_types(self) -> None:
        policy = load_policy("chart-policy/demo-1.0")
        self.assertEqual(select_chart(VisualTarget("a", "trend"), policy)["chart_type"], "line")
        self.assertEqual(select_chart(VisualTarget("b", "relationship"), policy)["chart_type"], "scatter")
        self.assertEqual(select_chart(VisualTarget("c", "matrix"), policy)["chart_type"], "heatmap")

    def test_invalid_llm_or_user_preference_falls_back_to_safe_type(self) -> None:
        policy = load_policy("chart-policy/demo-1.0")
        decision = select_chart(VisualTarget("a", "trend", preferred_chart_type="pie"), policy, llm_suggestion="waterfall")
        self.assertEqual(decision["chart_type"], "line")
        self.assertEqual(decision["reason_code"], "SEL_POLICY_VISUAL_QUESTION")

    def test_valid_structured_llm_decision_can_override_user_preference(self) -> None:
        policy = load_policy("chart-policy/demo-1.0")

        decision = select_chart(
            VisualTarget("a", "trend", preferred_chart_type="line"),
            policy,
            llm_suggestion={"selected_chart_type": "area", "candidates": [{"chart_type": "area"}]},
        )

        self.assertEqual(decision["chart_type"], "area")
        self.assertEqual(decision["reason_code"], "SEL_LLM_ACCEPTED")
        self.assertEqual(decision["llm_candidates"], [{"chart_type": "area"}])

    def test_accepts_area_as_a_policy_compatible_trend_representation(self) -> None:
        policy = load_policy("chart-policy/demo-1.0")

        decision = select_chart(VisualTarget("a", "trend", preferred_chart_type="area"), policy)

        self.assertEqual(decision["chart_type"], "area")
        self.assertEqual(decision["reason_code"], "SEL_PREFERENCE_ACCEPTED")

    def test_supports_the_complete_visual_question_catalog(self) -> None:
        policy = load_policy("chart-policy/demo-1.0")
        cases = {
            "current_value": "kpi_card", "comparison": "bar", "distribution_comparison": "box_plot",
            "geospatial": "map", "additive_change": "waterfall", "hierarchy": "treemap", "actual_vs_target": "bullet",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(select_chart(VisualTarget(question, question), policy)["chart_type"], expected)
