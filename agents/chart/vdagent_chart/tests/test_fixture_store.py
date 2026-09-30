from __future__ import annotations

import unittest

from vdagent_chart.contracts import ArtifactRef
from vdagent_chart.fixture_store import FixtureArtifactStore


class FixtureStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FixtureArtifactStore.demo()

    def test_resolves_the_exact_pinned_artifact(self) -> None:
        artifact = self.store.get_exact(ArtifactRef("metric_dom_target", 1, "sha256:metric-dom-target-v1"))

        self.assertEqual(artifact["artifact_id"], "metric_dom_target")
        self.assertEqual(artifact["version"], 1)
        self.assertEqual(artifact["payload"]["unit"], "day")

    def test_rejects_missing_or_hash_mismatched_artifacts(self) -> None:
        with self.assertRaisesRegex(Exception, "not found"):
            self.store.get_exact(ArtifactRef("missing", 1))
        with self.assertRaisesRegex(Exception, "hash"):
            self.store.get_exact(ArtifactRef("metric_dom_target", 1, "sha256:wrong"))
