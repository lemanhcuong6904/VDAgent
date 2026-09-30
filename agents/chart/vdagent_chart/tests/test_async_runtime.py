from __future__ import annotations

import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart import make_reasoner
from vdagent_chart.llm import OpenAIVisualReasoner
from vdagent_chart.service import ChartAgentService
from vdagent_chart.settings import Settings
from vdagent_chart.telemetry import InMemoryTelemetry


def test_telemetry_removes_sensitive_keys_and_values():
    from vdagent_chart.telemetry import safe_attributes

    attributes = safe_attributes(
        {"status": "success", "prompt": "ignore this", "api_key": "sk-secret", "trace_id": "trace-1", "note": "a@b.com"}
    )

    assert attributes == {"status": "success", "trace_id": "trace-1"}


class FailingReasoner:
    async def suggest(self, visual_question: str, allowed_chart_types: tuple[str, ...]) -> str | None:
        raise TimeoutError("provider unavailable")


class CapturingReasoner:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def decide(self, payload: dict, allowed_chart_types: tuple[str, ...]) -> dict:
        self.payloads.append(payload)
        return {"selection": {"chart_type": "scatter"}, "presentation": {"title": "Synthetic relationship"}}


class AsyncRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_reasoner_factory_uses_gpt_4o_mini_only_when_openai_is_configured(self) -> None:
        reasoner = make_reasoner(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
                "LLM_MODEL": "gpt-4o-mini",
            }
        )

        self.assertIsInstance(reasoner, OpenAIVisualReasoner)
        self.assertIsNone(make_reasoner({}))

    async def test_llm_failure_keeps_deterministic_result_and_emits_safe_events(self) -> None:
        telemetry = InMemoryTelemetry()
        service = ChartAgentService(
            FixtureArtifactStore.demo(), reasoner=FailingReasoner(), telemetry=telemetry
        )

        result = await service.execute_async(load_demo_task("price_trend"))

        self.assertEqual(result.status, "success")
        self.assertEqual([event.name for event in telemetry.events], [
            "chart.started", "chart.llm.unavailable", "chart.completed"
        ])
        self.assertNotIn("visual_question", telemetry.events[1].attributes)
        self.assertNotIn("OPENAI_API_KEY", str(telemetry.events))

    async def test_llm_receives_synthetic_insight_and_comparison_context(self) -> None:
        reasoner = CapturingReasoner()
        service = ChartAgentService(FixtureArtifactStore.demo(), reasoner=reasoner)

        result = await service.execute_async(load_demo_task("rich_context_relationship"))

        self.assertEqual(result.status, "success")
        artifact_types = {artifact["artifact_type"] for artifact in reasoner.payloads[0]["artifacts"]}
        artifact_ids = {artifact["artifact_id"] for artifact in reasoner.payloads[0]["artifacts"]}
        self.assertIn("insight", artifact_types)
        self.assertIn("comparison", artifact_types)
        self.assertIn("insight_synthetic_price_dom", artifact_ids)
        self.assertIn("comparison_synthetic_price_dom_segments", artifact_ids)

    async def test_openai_reasoner_supports_mock_upstream_json_methods(self) -> None:
        calls: list[str] = []

        async def fake_completion(**kwargs):
            content = kwargs["messages"][0]["content"]
            calls.append(content)
            if "LLM Orchestrator" in content:
                payload = {"visual_question": "composition", "preferred_chart_type": "pie", "data_grain": "segment"}
            elif "LLM Data Agent" in content:
                payload = {"metric_id": "inventory_mix", "grain": "segment", "unit": "units", "records": [{"label": "2BR", "count": 10}]}
            elif "LLM Insight Agent" in content:
                payload = {"claim": "2BR is largest.", "confidence": 0.8}
            elif "LLM Compare Agent" in content:
                payload = {"comparison_metric": "share", "display_records": [{"label": "2BR", "share": 1.0}]}
            else:
                payload = {"title": "Cơ cấu tồn kho căn hộ theo loại phòng tại VHOP", "subtitle": "Tỷ trọng theo số căn."}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(payload)))])

        fake_litellm = SimpleNamespace(acompletion=fake_completion)
        reasoner = OpenAIVisualReasoner(Settings("test-key", "https://api.openai.com/v1", "gpt-4o-mini", 5))

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            plan = await reasoner.decide_orchestration("Cơ cấu tồn kho", ("pie", "bar"))
            metric = await reasoner.generate_metric_artifact(plan)
            insight = await reasoner.generate_insight_artifact(plan, metric)
            comparison = await reasoner.generate_comparison_artifact(plan, metric, insight)
            presentation = await reasoner.generate_presentation_plan(plan, metric, insight, comparison)

        self.assertEqual(plan["visual_question"], "composition")
        self.assertEqual(metric["records"][0]["count"], 10)
        self.assertEqual(insight["confidence"], 0.8)
        self.assertEqual(comparison["display_records"][0]["share"], 1.0)
        self.assertEqual(presentation["title"], "Cơ cấu tồn kho căn hộ theo loại phòng tại VHOP")
        self.assertEqual(len(calls), 5)
