from __future__ import annotations

import unittest

from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.mock_upstream import build_mock_upstream, run_mock_upstream_pipeline
from vdagent_chart.service import ChartAgentService


class MockUpstreamTests(unittest.TestCase):
    def test_relationship_question_builds_complete_virtual_upstream_bundle(self) -> None:
        bundle = build_mock_upstream("So sánh giá/m2 và DOM của các căn hộ VHOP")

        self.assertEqual(bundle.task.visual_targets[0].visual_question, "relationship")
        self.assertEqual(
            {artifact["artifact_type"] for artifact in bundle.artifacts},
            {"metric", "insight", "comparison"},
        )
        self.assertEqual(
            bundle.llm_suggestions[bundle.task.visual_targets[0].target_id]["selection"]["chart_type"],
            "scatter",
        )

        result = ChartAgentService(FixtureArtifactStore(bundle.artifacts)).execute(
            bundle.task,
            bundle.llm_suggestions,
        )

        self.assertEqual(result.status, "success")


class AsyncMockUpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_uses_llm_upstream_reasoner_outputs_to_build_chart_inputs(self) -> None:
        class FakeLLMUpstream:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def decide_orchestration(self, question, allowed_chart_types):
                self.calls.append("orchestrator")
                return {
                    "visual_question": "composition",
                    "preferred_chart_type": "pie",
                    "data_grain": "segment",
                    "encoding": {
                        "theta": {"field": "count", "type": "quantitative"},
                        "color": {"field": "label", "type": "nominal"},
                    },
                    "candidates": [{"chart_type": "pie", "reason": "composition question"}],
                }

            async def generate_metric_artifact(self, plan):
                self.calls.append("data")
                return {
                    "metric_id": "llm_inventory_mix",
                    "grain": "segment",
                    "unit": "units",
                    "records": [
                        {"label": "1BR", "count": 48},
                        {"label": "2BR", "count": 120},
                        {"label": "3BR", "count": 64},
                    ],
                }

            async def generate_insight_artifact(self, plan, metric_payload):
                self.calls.append("insight")
                return {
                    "insight_id": "llm_inventory_mix_insight",
                    "claim": "2BR inventory is the largest synthetic segment.",
                    "confidence": 0.77,
                }

            async def generate_comparison_artifact(self, plan, metric_payload, insight_payload):
                self.calls.append("compare")
                return {
                    "comparison_id": "llm_inventory_mix_comparison",
                    "comparison_metric": "inventory_share",
                    "display_records": [
                        {"label": "1BR", "share": 0.21},
                        {"label": "2BR", "share": 0.52},
                        {"label": "3BR", "share": 0.27},
                    ],
                }

            async def generate_presentation_plan(self, plan, metric_payload, insight_payload, comparison_payload):
                self.calls.append("presentation")
                return {
                    "title": "Cơ cấu tồn kho căn hộ theo loại phòng tại VHOP",
                    "subtitle": "Tỷ trọng số lượng căn theo 1BR, 2BR và 3BR.",
                }

        reasoner = FakeLLMUpstream()

        bundle = await run_mock_upstream_pipeline(
            "Cơ cấu tồn kho theo loại căn hộ",
            reasoner=reasoner,
        )

        self.assertEqual(reasoner.calls, ["orchestrator", "data", "insight", "compare", "presentation"])
        self.assertEqual(bundle.task.visual_targets[0].visual_question, "composition")
        self.assertEqual(bundle.task.visual_targets[0].preferred_chart_type, "pie")
        self.assertEqual(bundle.artifacts[0]["payload"]["metric_id"], "llm_inventory_mix")
        self.assertEqual(
            bundle.llm_suggestions[bundle.task.visual_targets[0].target_id]["selection"]["chart_type"],
            "pie",
        )
        self.assertEqual(
            bundle.llm_suggestions[bundle.task.visual_targets[0].target_id]["presentation"]["title"],
            "Cơ cấu tồn kho căn hộ theo loại phòng tại VHOP",
        )

        result = ChartAgentService(FixtureArtifactStore(bundle.artifacts)).execute(
            bundle.task,
            bundle.llm_suggestions,
        )

        self.assertEqual(result.status, "success")
        self.assertRegex(result.chart_artifacts[0], r"^chart_mock_chart_task_[0-9a-f]{12}_vt_llm_composition@1$")

    def test_funnel_question_prefers_funnel_visual_question_and_chart_type(self) -> None:
        bundle = build_mock_upstream("Vẽ phễu bán hàng từ Visit đến Contract")

        self.assertEqual(bundle.task.visual_targets[0].visual_question, "funnel")
        self.assertEqual(
            bundle.llm_suggestions[bundle.task.visual_targets[0].target_id]["selection"]["chart_type"],
            "funnel",
        )

    def test_peer_question_builds_target_vs_peer_bundle_with_peer_definition(self) -> None:
        bundle = build_mock_upstream("So sánh DOM căn A12-08 với peer group cùng phân khu")

        self.assertEqual(bundle.task.visual_targets[0].visual_question, "target_vs_peer")
        comparison = next(artifact for artifact in bundle.artifacts if artifact["artifact_type"] == "comparison")
        self.assertEqual(comparison["payload"]["peer_definition"]["peer_count"], 24)
        self.assertEqual(
            bundle.llm_suggestions[bundle.task.visual_targets[0].target_id]["selection"]["chart_type"],
            "bar",
        )

        result = ChartAgentService(FixtureArtifactStore(bundle.artifacts)).execute(
            bundle.task,
            bundle.llm_suggestions,
        )

        self.assertEqual(result.status, "success")
