from __future__ import annotations

import unittest

from vdagent_chart.errors import ChartError
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.policy import load_policy
from vdagent_chart.resolution import resolve_context


class ResolutionTests(unittest.TestCase):
    def test_resolves_only_pinned_artifacts_into_a_typed_context(self) -> None:
        task = load_demo_task("price_trend")

        context = resolve_context(task, FixtureArtifactStore.demo(), load_policy(task.policy_ref))

        self.assertEqual(context.task.task_id, task.task_id)
        self.assertEqual(context.artifacts[0].artifact_id, "metric_price_trend")
        self.assertEqual(context.validation["overall_result"], "pass")

    def test_missing_exact_ref_becomes_a_structured_dependency_error(self) -> None:
        task = load_demo_task("missing_dependency")

        with self.assertRaises(ChartError) as caught:
            resolve_context(task, FixtureArtifactStore.demo(), load_policy(task.policy_ref))

        self.assertEqual(caught.exception.code, "DEP-002")
        self.assertEqual(caught.exception.details["artifact_id"], "metric_not_ready")
