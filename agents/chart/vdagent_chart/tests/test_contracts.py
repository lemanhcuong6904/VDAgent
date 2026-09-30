from __future__ import annotations

import unittest

from vdagent_chart.contracts import ChartTaskResult, TargetResult


class ContractTests(unittest.TestCase):
    def test_partial_result_preserves_per_target_status_and_structured_error(self) -> None:
        result = ChartTaskResult(
            schema_version="chart-result/2.0",
            run_id="run_1",
            task_id="task_1",
            status="partial",
            target_results=(TargetResult("target_ok", "success", "chart_x@1"), TargetResult("target_bad", "failed", reason_code="DEP-002")),
            errors=({"code": "DEP-002", "category": "dependency", "retryable": False, "target_id": "target_bad"},),
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.target_results[1].reason_code, "DEP-002")
        self.assertEqual(result.errors[0]["category"], "dependency")

    def test_chart_spec_includes_required_lineage_and_validation_metadata(self) -> None:
        from vdagent_chart.contracts import ChartSpecArtifact

        spec = ChartSpecArtifact("chart_1", 1, "validated", "line", "Trend", {}, {}, {"input_artifact_refs": ["m_1@1"]}, {"overall_result": "pass"}, "sha256:x", limitations=("freshness warning",))
        self.assertIn("input_artifact_refs", spec.lineage)
        self.assertEqual(spec.validation["overall_result"], "pass")
        self.assertEqual(spec.limitations, ("freshness warning",))
