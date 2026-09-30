from __future__ import annotations

import unittest

from vdagent_chart.compatibility import compatibility_errors
from vdagent_chart.profile import DataProfile


class CompatibilityTests(unittest.TestCase):
    def test_line_requires_a_time_dimension_and_two_records(self) -> None:
        profile = DataProfile(1, ("price_m2",), ("label",), False, "month", "VND/m2")

        errors = compatibility_errors("line", profile)

        self.assertEqual(errors[0].code, "DAT-002")

    def test_scatter_requires_two_numeric_metrics(self) -> None:
        profile = DataProfile(3, ("dom",), ("unit_id",), False, "unit", "day")

        errors = compatibility_errors("scatter", profile)

        self.assertEqual(errors[0].code, "DAT-008")
