from __future__ import annotations

import unittest

from vdagent_chart.agent import ChartPluginAgent
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.service import ChartAgentService


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_command_emits_chart_reference(self) -> None:
        class Ctx:
            history = [{"role": "user", "content": "chart demo price_trend"}]
            emitted: list[str] = []
            async def emit_assistant(self, content, tool_calls=()): self.emitted.append(content)
        ctx = Ctx()
        await ChartPluginAgent(ChartAgentService(FixtureArtifactStore.demo())).invoke(ctx)
        self.assertIn("chart_chart_task_price_trend_vt_price_trend@1", ctx.emitted[-1])

    async def test_plugin_persists_to_context_artifact_store_when_available(self) -> None:
        class Store:
            async def save_chart_spec(self, **kwargs):
                self.kwargs = kwargs
                return {"id": "csp_0123456789ab", "version": 1}
        class Ctx:
            history = [{"role": "user", "content": "chart demo price_trend"}]
            emitted: list[str] = []
            artifacts = Store()
            async def emit_assistant(self, content, tool_calls=()): self.emitted.append(content)
        ctx = Ctx()

        await ChartPluginAgent(ChartAgentService(FixtureArtifactStore.demo())).invoke(ctx)

        self.assertIn("csp_0123456789ab@1", ctx.emitted[-1])

    async def test_persisted_demo_idempotency_key_is_scoped_to_chart_content(self) -> None:
        class Store:
            def __init__(self) -> None:
                self.idempotency_key = ""

            async def save_chart_spec(self, **kwargs):
                self.idempotency_key = kwargs["idempotency_key"]
                return {"id": "csp_0123456789ab", "version": 1}

        class Ctx:
            history = [{"role": "user", "content": "chart demo price_trend"}]
            emitted: list[str] = []
            artifacts = Store()

            async def emit_assistant(self, content, tool_calls=()):
                self.emitted.append(content)

        ctx = Ctx()

        await ChartPluginAgent(ChartAgentService(FixtureArtifactStore.demo())).invoke(ctx)

        self.assertRegex(
            ctx.artifacts.idempotency_key,
            r"^price-trend-v1:chart_chart_task_price_trend_vt_price_trend@1:sha256:[0-9a-f]{64}$",
        )

    async def test_natural_language_chart_ask_runs_mock_upstream_before_real_chart_agent(self) -> None:
        class Store:
            def __init__(self) -> None:
                self.kwargs = {}

            async def save_chart_spec(self, **kwargs):
                self.kwargs = kwargs
                return {"id": "csp_mock_pipeline", "version": 1}

        class Ctx:
            history = [{"role": "user", "content": "chart ask So sánh giá/m2 và DOM của các căn hộ VHOP"}]
            emitted: list[str] = []
            artifacts = Store()

            async def emit_assistant(self, content, tool_calls=()):
                self.emitted.append(content)

        ctx = Ctx()

        await ChartPluginAgent(ChartAgentService(FixtureArtifactStore.demo())).invoke(ctx)

        self.assertIn("Mock upstream", ctx.emitted[-1])
        self.assertIn("csp_mock_pipeline@1", ctx.emitted[-1])
        transcript = "\n".join(ctx.emitted)
        for expected in (
            "Orchestrator running",
            "Orchestrator output",
            "Data Agent running",
            "Data Agent output",
            "Insight Agent running",
            "Insight Agent output",
            "Compare Agent running",
            "Compare Agent output",
            "Chart Agent running",
        ):
            self.assertIn(expected, transcript)
        self.assertEqual(ctx.artifacts.kwargs["chart_spec"]["chart_type"], "scatter")
        self.assertEqual(ctx.artifacts.kwargs["chart_spec"]["visual_question"], "relationship")
        self.assertGreaterEqual(len(ctx.artifacts.kwargs["lineage"]["input_artifact_refs"]), 3)

    async def test_chart_ask_uses_injected_llm_upstream_reasoner(self) -> None:
        class FakeLLMUpstream:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def decide_orchestration(self, question, allowed_chart_types):
                self.calls.append("orchestrator")
                return {
                    "visual_question": "composition",
                    "preferred_chart_type": "pie",
                    "data_grain": "segment",
                }

            async def generate_metric_artifact(self, plan):
                self.calls.append("data")
                return {
                    "metric_id": "llm_inventory_mix",
                    "grain": "segment",
                    "unit": "units",
                    "records": [{"label": "2BR", "count": 120}, {"label": "3BR", "count": 64}],
                }

            async def generate_insight_artifact(self, plan, metric_payload):
                self.calls.append("insight")
                return {"claim": "2BR inventory is largest.", "confidence": 0.7}

            async def generate_comparison_artifact(self, plan, metric_payload, insight_payload):
                self.calls.append("compare")
                return {
                    "comparison_metric": "share",
                    "display_records": [{"label": "2BR", "share": 0.65}, {"label": "3BR", "share": 0.35}],
                }

            async def generate_presentation_plan(self, plan, metric_payload, insight_payload, comparison_payload):
                self.calls.append("presentation")
                return {
                    "title": "Cơ cấu tồn kho căn hộ theo loại phòng tại VHOP",
                    "subtitle": "Tỷ trọng tồn kho theo 2BR và 3BR.",
                }

        class Store:
            async def save_chart_spec(self, **kwargs):
                self.kwargs = kwargs
                return {"id": "csp_llm_pipeline", "version": 1}

        class Ctx:
            history = [{"role": "user", "content": "chart ask Cơ cấu tồn kho theo loại căn hộ"}]
            emitted: list[str] = []
            artifacts = Store()

            async def emit_assistant(self, content, tool_calls=()):
                self.emitted.append(content)

        reasoner = FakeLLMUpstream()
        ctx = Ctx()

        await ChartPluginAgent(
            ChartAgentService(FixtureArtifactStore.demo()),
            upstream_reasoner=reasoner,
        ).invoke(ctx)

        self.assertEqual(reasoner.calls, ["orchestrator", "data", "insight", "compare", "presentation"])
        self.assertEqual(ctx.artifacts.kwargs["chart_spec"]["visual_question"], "composition")
        self.assertEqual(ctx.artifacts.kwargs["chart_spec"]["chart_type"], "pie")
        self.assertEqual(
            ctx.artifacts.kwargs["chart_spec"]["presentation"]["title"],
            "Cơ cấu tồn kho căn hộ theo loại phòng tại VHOP",
        )
        self.assertIn("csp_llm_pipeline@1", ctx.emitted[-1])
