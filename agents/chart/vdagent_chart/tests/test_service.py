from __future__ import annotations

import unittest
from dataclasses import replace

from vdagent_chart.contracts import VisualTarget
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.service import ChartAgentService


class ServiceTests(unittest.TestCase):
    def test_all_standard_demo_scenarios_produce_chart_artifacts(self) -> None:
        service = ChartAgentService(FixtureArtifactStore.demo())

        for scenario in (
            "dom_peer",
            "price_trend",
            "inventory_composition",
            "dom_distribution",
            "price_dom_relationship",
            "sales_funnel",
            "area_month_heatmap",
        ):
            with self.subTest(scenario=scenario):
                result = service.execute(load_demo_task(scenario))
                self.assertEqual(result.status, "success")
                self.assertTrue(result.chart_artifacts)

    def test_creates_a_validated_chart_spec_for_a_demo_task(self) -> None:
        result = ChartAgentService(FixtureArtifactStore.demo()).execute(load_demo_task("price_trend"))
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.chart_artifacts), 1)

    def test_returns_structured_dependency_request_without_hallucinating(self) -> None:
        result = ChartAgentService(FixtureArtifactStore.demo()).execute(load_demo_task("missing_dependency"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.dependency_requests[0]["artifact_id"], "metric_not_ready")

    def test_keeps_independent_targets_when_one_cannot_resolve_a_metric(self) -> None:
        task = load_demo_task("price_trend")
        broken = VisualTarget("broken", "trend", artifact_ids=("metric_not_available",))
        result = ChartAgentService(FixtureArtifactStore.demo()).execute(
            replace(task, visual_targets=(task.visual_targets[0], broken))
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.chart_artifacts), 1)
        self.assertEqual(result.target_results[0].status, "success")
        self.assertEqual(result.target_results[1].reason_code, "DEP-005")
        self.assertEqual(result.errors[0]["target_id"], "broken")

    def test_uses_llm_chart_plan_for_selection_encoding_and_presentation_under_guardrails(self) -> None:
        service = ChartAgentService(FixtureArtifactStore.demo())
        task = load_demo_task("line")

        result = service.execute(
            task,
            {
                "vt_line": {
                    "selection": {"chart_type": "area", "reason_codes": ["LLM_SEMANTIC_MATCH"]},
                    "encoding": {
                        "x": {"field": "invented_month", "type": "temporal"},
                        "y": {"field": "price_m2", "type": "quantitative"},
                    },
                    "presentation": {"title": "Price movement", "subtitle": "LLM-authored presentation"},
                }
            },
        )

        artifact = service.artifacts[result.chart_artifacts[0].removesuffix("@1")]
        self.assertEqual(artifact["semantic_spec"]["chart_type"], "area")
        self.assertEqual(artifact["semantic_spec"]["presentation"]["title"], "Price movement")
        self.assertEqual(artifact["semantic_spec"]["encoding"]["x"]["field"], "month")
        self.assertEqual(artifact["semantic_spec"]["encoding"]["y"]["field"], "price_m2")
