from __future__ import annotations

import unittest

from vdagent_chart.dataset import assemble_dataset
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.evidence import build_evidence_map
from vdagent_chart.policy import load_policy
from vdagent_chart.resolution import resolve_context


class DatasetTests(unittest.TestCase):
    def test_typed_assembly_declares_null_handling_and_transform_log(self) -> None:
        task = load_demo_task("price_trend")
        context = resolve_context(task, FixtureArtifactStore.demo(), load_policy(task.policy_ref))
        binding = build_evidence_map(context)["vt_price_trend"]

        data = assemble_dataset(context, binding, {"chart_type": "line"})

        self.assertEqual(data["null_handling"], "preserve")
        self.assertEqual(data["presentation_transforms"], [])
        self.assertEqual(data["mode"], "inline")

    def test_target_vs_peer_uses_the_validated_comparison_values_and_peer_context(self) -> None:
        task = load_demo_task("dom_peer")
        store = FixtureArtifactStore.demo()
        artifacts = [store.get_exact(ref) for ref in task.artifact_refs]

        data = assemble_dataset(task.visual_targets[0], artifacts, {"chart_type": "bar"})

        self.assertEqual(
            data["records"],
            [
                {"label": "A12-08", "dom": 126.0, "cohort": "target"},
                {"label": "Peer - A01", "dom": 87.0, "cohort": "peer"},
                {"label": "Peer - A02", "dom": 94.0, "cohort": "peer"},
                {"label": "Peer - A03", "dom": 91.0, "cohort": "peer"},
            ],
        )
        self.assertEqual(data["peer_definition"]["peer_count"], 24)
        self.assertEqual(data["peer_population"]["members"][0]["unit_id"], "A12-09")
        self.assertEqual(data["unit"], "day")

    def test_assembly_preserves_values_nulls_and_a_stable_hash(self) -> None:
        task = load_demo_task("price_trend")
        store = FixtureArtifactStore.demo()
        artifacts = [store.get_exact(ref) for ref in task.artifact_refs]
        first = assemble_dataset(task.visual_targets[0], artifacts, {"chart_type": "line"})
        second = assemble_dataset(task.visual_targets[0], artifacts, {"chart_type": "line"})

        self.assertEqual(first["records"], artifacts[0]["payload"]["records"])
        self.assertEqual(first["dataset_hash"], second["dataset_hash"])
        self.assertEqual(first["presentation_transforms"], [])

    def test_assembly_rejects_silent_top_n_and_never_changes_null_to_zero(self) -> None:
        task = load_demo_task("price_trend")
        store = FixtureArtifactStore.demo()
        artifacts = [store.get_exact(ref) for ref in task.artifact_refs]
        artifacts[0]["payload"]["records"][1]["price_m2"] = None

        data = assemble_dataset(task.visual_targets[0], artifacts, {"chart_type": "line"})
        self.assertIsNone(data["records"][1]["price_m2"])
        with self.assertRaisesRegex(Exception, "top-N"):
            assemble_dataset(task.visual_targets[0], artifacts, {"chart_type": "line", "top_n": 1})
