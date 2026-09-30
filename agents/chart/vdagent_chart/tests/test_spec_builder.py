from vdagent_chart.spec_builder import build_semantic_spec


def test_builds_chart_spec_v2_with_audit_fields():
    spec = build_semantic_spec(
        chart_id="chart_x", task_id="task_x", target_id="target_x", chart_type="bar",
        purpose="direct_visualization", visual_question="target_vs_peer",
        scope={"snapshot_id": "2026-06-30", "data_grain": "group"},
        dataset={"schema": [], "records": [{"month": "2026-01", "value": 1}], "dataset_hash": "sha256:x"},
        selection={"reason_code": "SEL"}, presentation={"title": "Title"},
        lineage={"input_artifact_refs": ["metric_x@1"]}, validation={"overall_result": "pass"},
    )
    assert spec["schema_version"] == "chart-spec/2.0"
    assert spec["visual_target_ids"] == ["target_x"]
    assert spec["lineage"]["input_artifact_refs"] == ["metric_x@1"]
    assert spec["encoding"]["x"]["field"] == "month"
