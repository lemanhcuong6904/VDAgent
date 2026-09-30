from vdagent_chart.output_validation import validate_chart_spec


def test_rejects_semantic_spec_without_exact_lineage():
    outcome = validate_chart_spec({"schema_version": "chart-spec/2.0", "dataset": {"records": []}})
    assert outcome["overall_result"] == "fail"
    assert "lineage" in outcome["checks"]


def test_rejects_causal_or_pii_presentation_text():
    spec = {
        "schema_version": "chart-spec/2.0", "dataset": {"records": [], "dataset_hash": "sha256:x"},
        "lineage": {"input_artifact_refs": ["metric@1"]}, "presentation": {"title": "DOM causes sales a@b.com"},
    }
    outcome = validate_chart_spec(spec)
    assert outcome["overall_result"] == "fail"
    assert "presentation" in outcome["failures"]


def test_rejects_dataset_with_a_grain_that_conflicts_with_scope():
    spec = {
        "schema_version": "chart-spec/2.0",
        "scope": {"snapshot_id": "2026-06-30", "data_grain": "month"},
        "dataset": {"records": [{"month": "2026-01", "value": 1}], "dataset_hash": "sha256:x", "grain": "unit"},
        "encoding": {"x": {"field": "month"}, "y": {"field": "value"}},
        "lineage": {"input_artifact_refs": ["metric_x@1"]},
        "presentation": {"title": "Monthly value"},
    }

    outcome = validate_chart_spec(spec)

    assert outcome["overall_result"] == "fail"
    assert "scope" in outcome["failures"]
