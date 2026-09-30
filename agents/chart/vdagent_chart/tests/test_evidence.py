from __future__ import annotations

import unittest

from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.policy import load_policy
from vdagent_chart.resolution import resolve_context
from vdagent_chart.evidence import build_evidence_map


class EvidenceMapTests(unittest.TestCase):
    def test_target_vs_peer_binds_metrics_evidence_and_comparison(self) -> None:
        task = load_demo_task("dom_peer")
        context = resolve_context(task, FixtureArtifactStore.demo(), load_policy(task.policy_ref))

        binding = build_evidence_map(context)["vt_dom_peer"]

        self.assertEqual(binding.metric_ids, ("metric_dom_target", "metric_dom_peer"))
        self.assertEqual(binding.evidence_ids, ("evidence_dom_peer",))
        self.assertEqual(binding.comparison_ids, ("comparison_dom_peer",))
