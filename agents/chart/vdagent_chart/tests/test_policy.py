from __future__ import annotations

import unittest

from vdagent_chart.policy import load_policy


class PolicyTests(unittest.TestCase):
    def test_demo_policy_is_pinned_and_forbids_unsafe_global_transforms(self) -> None:
        policy = load_policy("chart-policy/demo-1.0")

        self.assertEqual(policy.ruleset_version, "chart-policy/demo-1.0")
        self.assertIn("line", policy.allowed_chart_types)
        self.assertIn("table", policy.allowed_chart_types)
        self.assertFalse(policy.allow_dual_axis)
        self.assertFalse(policy.allow_imputation)
        self.assertFalse(policy.allow_silent_truncation)

    def test_rejects_an_unknown_policy_version(self) -> None:
        with self.assertRaisesRegex(Exception, "unknown chart policy"):
            load_policy("chart-policy/does-not-exist")
