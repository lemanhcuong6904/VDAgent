from __future__ import annotations

import copy
import unittest

from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.policy import load_policy
from vdagent_chart.validation import validate_input


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        task = load_demo_task("price_trend")
        store = FixtureArtifactStore.demo()
        self.task = task
        self.artifacts = [store.get_exact(ref) for ref in task.artifact_refs]
        self.policy = load_policy(task.policy_ref)

    def test_accepts_matching_validated_artifacts(self) -> None:
        summary = validate_input(self.task, self.artifacts, self.policy)

        self.assertEqual(summary["overall_result"], "pass")
        self.assertIn("scope", summary["checks"])

    def test_rejects_run_scope_or_grain_conflicts_before_reasoning(self) -> None:
        wrong_run = copy.deepcopy(self.artifacts)
        wrong_run[0]["run_id"] = "other-run"
        with self.assertRaisesRegex(Exception, "run_id"):
            validate_input(self.task, wrong_run, self.policy)

        wrong_grain = copy.deepcopy(self.artifacts)
        wrong_grain[0]["scope"]["data_grain"] = "unit"
        with self.assertRaisesRegex(Exception, "grain"):
            validate_input(self.task, wrong_grain, self.policy)
