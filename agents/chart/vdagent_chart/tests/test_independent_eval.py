from __future__ import annotations

import unittest

from vdagent_chart.agent import ChartPluginAgent
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.independent_eval import (
    build_independent_evaluation,
    live_runner_report,
    plan_upstream_simulation_with_repair,
    run_evaluation_suite,
    run_golden_evaluation_suite,
    run_independent_evaluation,
    run_persisted_evaluation_suite,
)
from vdagent_chart.service import ChartAgentService
from vdagent_contracts.vega_lite import validate_vega_lite
from vdagent_sdk import McpEndpoint


class Ctx:
    def __init__(self, text: str) -> None:
        self.invocation_id, self.task_id, self.user_id = "inv_chart_eval", "t_chart_eval", "u_000000000001"
        self.summary, self.peers, self.max_steps = "", [], 12
        self.history = [{"role": "user", "content": f"[from: user] {text}"}]
        self.mcp = McpEndpoint(url="http://mcp.test/mcp", token="tok")
        self.steps: list[tuple[str, list[object]]] = []

    async def emit_assistant(self, content: str, tool_calls: object = ()) -> None:
        self.steps.append((content, list(tool_calls or [])))


class IndependentEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_plan_is_repaired_before_artifacts_are_generated(self) -> None:
        class BadPlanner:
            async def plan_upstream_simulation(self, question, allowed_metrics):
                return {
                    "subject_unit_code": "drop table",
                    "metrics": ["dom", "invented_metric"],
                    "peer_count": 99,
                    "mode": "invent_facts",
                }

        plan = await plan_upstream_simulation_with_repair("Vì sao MAS-U00015 bán chậm?", reasoner=BadPlanner())

        self.assertEqual(plan.subject_unit_code, "MAS-U00015")
        self.assertEqual(plan.metrics, ("dom",))
        self.assertEqual(plan.peer_count, 12)
        self.assertEqual(plan.mode, "mock_real_data")
        self.assertIn("peer_count_clamped", plan.repair_notes)

    async def test_canonical_mock_artifacts_run_through_the_stepspec_product_path(self) -> None:
        experiment = build_independent_evaluation("Vì sao MAS-U00283 bán chậm? Hãy trực quan hóa.")

        report = await run_independent_evaluation(experiment)

        self.assertEqual(report.state, "completed", report)
        self.assertGreaterEqual(len(report.artifact_refs), 3)
        self.assertEqual(experiment.manifest["mode"], "mock_real_data")
        self.assertEqual(experiment.manifest["chart_path"], "StepSpec@1 -> run_step")
        self.assertTrue(experiment.manifest["contract_pass"])
        self.assertTrue(experiment.manifest["grounding_pass"])
        self.assertIn("warehouse/project_400", " ".join(experiment.manifest["source_refs"]))
        self.assertGreater(experiment.manifest["grounded_values"], 1)
        self.assertIn("SYNTHETIC_UPSTREAM_FOR_CHART_EVALUATION", experiment.manifest["limitations"])

        stored = [
            await experiment.tools.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})
            for ref in report.artifact_refs
        ]
        self.assertEqual({env["artifact_type"] for env in stored}, {"chart_spec"})
        for env in stored:
            self.assertEqual(env["producer"]["agent"], "chart")
            self.assertEqual(env["schema_version"], "chart_spec@1")
            self.assertEqual(env["snapshot_refs"], ["SNAP-20260630-01"])
            self.assertEqual(env["semantic_config_version"], "3.1.0")
            self.assertIn("SYNTHETIC_UPSTREAM_FOR_CHART_EVALUATION", env["limitations"])
            self.assertEqual(validate_vega_lite(env["payload"]["vega_lite"]), [])
            for binding in env["payload"]["bindings"]:
                ref, pointer = binding["source_ref"].split("#", 1)
                artifact_id, version = ref.split("@", 1)
                upstream = await experiment.tools.call("artifact_get", {"artifact_id": artifact_id, "version": int(version)})
                value = upstream["payload"]
                for token in pointer.split("/")[1:]:
                    value = value[int(token)] if isinstance(value, list) else value[token]
                self.assertEqual(str(value), binding["value_exact"])
        self.assertEqual(experiment.manifest["target_success"], len(report.artifact_refs))

    async def test_chart_eval_command_is_hard_disabled_without_the_flag(self) -> None:
        agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False, mock_upstream_enabled=False)
        ctx = Ctx("chart eval Vì sao MAS-U00283 bán chậm?")

        await agent.invoke(ctx)

        [(content, calls)] = ctx.steps
        self.assertEqual(calls, [])
        self.assertIn("CHART_MOCK_UPSTREAM=on", content)

    async def test_chart_eval_command_runs_isolated_harness_when_enabled(self) -> None:
        agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False, mock_upstream_enabled=True)
        ctx = Ctx("chart eval Vì sao MAS-U00283 bán chậm?")

        await agent.invoke(ctx)

        answer = "\n".join(content for content, _ in ctx.steps)
        self.assertIn("Mock Upstream Simulator", answer)
        self.assertIn("Chart Agent", answer)
        self.assertIn("chart_spec", answer)

    async def test_evaluation_suite_quantifies_peer_value_ablation(self) -> None:
        runs = await run_evaluation_suite("Vì sao MAS-U00283 bán chậm? Hãy trực quan hóa.")

        self.assertEqual([run.name for run in runs], ["FULL", "ABLATION:no_peer_values"])
        full, ablated = runs
        self.assertEqual(full.report.state, "completed")
        self.assertEqual(ablated.report.state, "completed")
        self.assertGreater(full.experiment.manifest["target_success"], ablated.experiment.manifest["target_success"])
        self.assertEqual(ablated.experiment.manifest["ablation"], "no_peer_values")

    async def test_persisted_suite_report_is_written_to_the_isolated_store(self) -> None:
        suite = await run_persisted_evaluation_suite("Vì sao MAS-U00283 bán chậm? Hãy trực quan hóa.")

        self.assertEqual(suite.name, "MOCK")
        self.assertEqual(suite.report["schema_version"], "chart_eval_report@1")
        self.assertTrue(suite.report_ref.startswith("mock_chart_eval_report_mock@"))
        report_id, version = suite.report_ref.split("@", 1)
        stored = await suite.runs[0].experiment.tools.call("artifact_get", {"artifact_id": report_id, "version": int(version)})
        self.assertEqual(stored["artifact_type"], "report")
        self.assertEqual(stored["schema_version"], "chart_eval_report@1")
        self.assertEqual(stored["payload"]["overall"]["state"], "PASS")

    async def test_golden_suite_uses_pinned_subject_and_persists_report(self) -> None:
        suite = await run_golden_evaluation_suite()

        self.assertEqual(suite.name, "GOLDEN")
        self.assertTrue(suite.report_ref.startswith("mock_chart_eval_report_golden@"))
        self.assertEqual([run.experiment.manifest["subject_unit_code"] for run in suite.runs], ["MAS-U00283", "MAS-U00283"])
        self.assertEqual([run.experiment.manifest["mode"] for run in suite.runs], ["golden", "golden"])

    async def test_live_runner_declares_required_real_artifacts(self) -> None:
        payload = live_runner_report("Vì sao MAS-U00283 bán chậm?")

        self.assertEqual(payload["state"], "not_run")
        self.assertIn("StepSpec@1", payload["expected_input"])

    async def test_chart_eval_suite_command_reports_full_and_ablation(self) -> None:
        agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False, mock_upstream_enabled=True)
        ctx = Ctx("chart eval suite Vì sao MAS-U00283 bán chậm?")

        await agent.invoke(ctx)

        [(answer, calls)] = ctx.steps
        self.assertEqual(calls, [])
        self.assertIn("FULL", answer)
        self.assertIn("ABLATION:no_peer_values", answer)
        self.assertIn("persisted_report", answer)
        self.assertIn("production StepSpec@1", answer)

    async def test_chart_eval_golden_and_live_commands_are_available(self) -> None:
        agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False, mock_upstream_enabled=True)
        golden = Ctx("chart eval golden")
        live = Ctx("chart eval live Vì sao MAS-U00283 bán chậm?")

        await agent.invoke(golden)
        await agent.invoke(live)

        self.assertIn("GOLDEN", golden.steps[0][0])
        self.assertIn("persisted_report", golden.steps[0][0])
        self.assertIn("LIVE Runner", live.steps[0][0])
        self.assertIn("not_run", live.steps[0][0])
