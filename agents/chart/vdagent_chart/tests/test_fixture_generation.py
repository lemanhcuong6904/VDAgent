from __future__ import annotations

import json
import unittest
from pathlib import Path

from vdagent_chart.fixtures import load_demo_task, scenario_names


ARTIFACTS_FILE = Path(__file__).parents[1] / "demo" / "artifacts.json"


class FixtureGenerationTests(unittest.TestCase):
    def test_demo_scenarios_cover_required_vhop_visual_questions(self) -> None:
        scenarios = set(scenario_names())

        self.assertTrue(
            {"dom_peer", "price_trend", "inventory_composition", "dom_distribution", "price_dom_relationship", "sales_funnel", "area_month_heatmap"}
            <= scenarios
        )

    def test_missing_dependency_task_keeps_an_exact_missing_ref(self) -> None:
        task = load_demo_task("missing_dependency")

        self.assertEqual(task.task_id, "chart_task_missing_dependency")
        self.assertTrue(any(ref.artifact_id == "metric_not_ready" and ref.required for ref in task.artifact_refs))

    def test_fixture_declares_its_vhop_snapshot_and_source_exports(self) -> None:
        source = json.loads(ARTIFACTS_FILE.read_text(encoding="utf-8"))["fixture_source"]

        self.assertEqual(source["snapshot_id"], "SNAP-20260630-01")
        self.assertEqual(
            set(source["exports"]),
            {"fact_unit_inventory_snapshot.csv", "fact_unit_price_history.csv", "fact_sales_funnel_daily.csv"},
        )
