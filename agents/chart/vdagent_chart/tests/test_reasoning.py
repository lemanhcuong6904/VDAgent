from __future__ import annotations

import unittest

from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task
from vdagent_chart.service import ChartAgentService


class ReasoningTests(unittest.TestCase):
    def test_applies_structured_llm_reasoning_to_encoding_and_presentation(self) -> None:
        service = ChartAgentService(FixtureArtifactStore.demo())

        result = service.execute(
            load_demo_task("dom_peer"),
            llm_suggestions={
                "vt_dom_peer": {
                    "selected_chart_type": "bar",
                    "candidates": [
                        {"chart_type": "bar", "reason": "compare target against peer cohorts"},
                        {"chart_type": "bullet", "reason": "single target against benchmark"},
                    ],
                    "encoding": {
                        "x": {"field": "label", "type": "nominal"},
                        "y": {"field": "dom", "type": "quantitative"},
                        "color": {"field": "cohort", "type": "nominal"},
                        "sort": {"field": "dom", "order": "descending"},
                    },
                    "presentation": {
                        "title": "DOM A12-08 vs comparable 2BR peers",
                        "subtitle": "24 peer units, 70-80 m2, same VHOP project",
                        "annotations": [{"type": "difference", "text": "+35 days vs benchmark"}],
                    },
                }
            },
        )

        artifact_id = result.chart_artifacts[0].removesuffix("@1")
        spec = service.artifacts[artifact_id]["semantic_spec"]
        self.assertEqual(spec["encoding"]["color"]["field"], "cohort")
        self.assertEqual(spec["selection"]["reason_code"], "SEL_LLM_ACCEPTED")
        self.assertEqual(spec["presentation"]["title"], "DOM A12-08 vs comparable 2BR peers")
        self.assertEqual(spec["presentation"]["annotations"][0]["text"], "+35 days vs benchmark")
