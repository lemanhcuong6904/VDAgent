from __future__ import annotations

import unittest

from vdagent_chart.evidence import build_evidence_map
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.policy import load_policy
from vdagent_chart.profile import profile_target
from vdagent_chart.resolution import resolve_context


class ProfileTests(unittest.TestCase):
    def test_profiles_time_series_shape_from_the_bound_metric(self) -> None:
        task = load_demo_task("price_trend")
        context = resolve_context(task, FixtureArtifactStore.demo(), load_policy(task.policy_ref))

        profile = profile_target(context, build_evidence_map(context)["vt_price_trend"])

        self.assertTrue(profile.has_time)
        self.assertEqual(profile.row_count, 3)
        self.assertEqual(profile.metric_fields, ("price_m2",))

    def test_profiles_comparison_display_records_without_mixing_source_grains(self) -> None:
        task = load_demo_task("dom_peer")
        context = resolve_context(task, FixtureArtifactStore.demo(), load_policy(task.policy_ref))

        profile = profile_target(context, build_evidence_map(context)["vt_dom_peer"])

        self.assertEqual(profile.row_count, 4)
        self.assertEqual(profile.grain, "group")
        self.assertEqual(profile.metric_fields, ("dom",))
        self.assertEqual(profile.dimension_fields, ("cohort", "label"))
