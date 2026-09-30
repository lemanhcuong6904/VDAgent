from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from vdagent_chart.errors import ChartError
from vdagent_chart.schema import normalize_artifact, parse_chart_task


TASKS_FILE = Path(__file__).parents[1] / "demo" / "tasks.json"
ARTIFACTS_FILE = Path(__file__).parents[1] / "demo" / "artifacts.json"


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
        self.task = next(task for task in tasks if task["name"] == "dom_peer")
        self.artifact = json.loads(ARTIFACTS_FILE.read_text(encoding="utf-8"))["artifacts"][0]

    def test_parses_a_pinned_demo_task_with_normalized_intent(self) -> None:
        task = parse_chart_task(self.task)

        self.assertEqual(task.schema_version, "chart-task/2.0")
        self.assertEqual(task.intent.purpose, "direct_visualization")
        self.assertEqual(task.visual_targets[0].target_id, "vt_dom_peer")
        self.assertEqual(task.artifact_refs[-1].version, 3)

    def test_rejects_unknown_or_invalid_task_fields_before_reasoning(self) -> None:
        unknown = copy.deepcopy(self.task)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ChartError, "unknown task fields"):
            parse_chart_task(unknown)

        invalid_mode = copy.deepcopy(self.task)
        invalid_mode["mode"] = "anything"
        with self.assertRaisesRegex(ChartError, "unsupported mode"):
            parse_chart_task(invalid_mode)

        invalid_ref = copy.deepcopy(self.task)
        invalid_ref["artifact_refs"][0]["version"] = "1"
        with self.assertRaisesRegex(ChartError, "integer version"):
            parse_chart_task(invalid_ref)

    def test_rejects_missing_snapshot_and_invalid_time_range(self) -> None:
        missing_snapshot = copy.deepcopy(self.task)
        del missing_snapshot["scope"]["snapshot_id"]
        with self.assertRaisesRegex(ChartError, "snapshot_id"):
            parse_chart_task(missing_snapshot)

        invalid_time = copy.deepcopy(self.task)
        invalid_time["scope"]["time_range"] = ["2026-06-30", "2026-01-01"]
        with self.assertRaisesRegex(ChartError, "time_range"):
            parse_chart_task(invalid_time)

    def test_normalizes_artifact_envelope(self) -> None:
        artifact = normalize_artifact(self.artifact)

        self.assertEqual(artifact.artifact_id, "metric_dom_target")
        self.assertEqual(artifact.artifact_type, "metric")
        self.assertEqual(artifact.scope.snapshot_id, "2026-06-30")
