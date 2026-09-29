from __future__ import annotations

from vdagent_contracts.catalogs import load_catalog
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import TaskKind
from vdagent_data.catalog import build_catalog

B02_ERROR_CLASSES = {
    "AMBIGUOUS_REQUEST": "NEED_INPUT",
    "ENTITY_NOT_FOUND": "SPEC_ISSUE",  # as an ERROR; with suggestions it is a QUESTION (no class needed)
    "SPEC_MISMATCH": "SPEC_ISSUE",
    "OUT_OF_SCOPE": "NO_ACCESS",
    "SIGNATURE_INVALID": "NO_ACCESS",
    "DATA_UNAVAILABLE": "NO_DATA",
    "DQ_BLOCKING": "DATA_QUALITY",
    "BUDGET_EXCEEDED": "SPEC_ISSUE",
    "LLM_UNAVAILABLE": "TRANSIENT",
    "LLM_QUOTA_EXHAUSTED": "QUOTA_EXHAUSTED",
    "INTERNAL_ERROR": "FATAL",
}


def test_catalog_four_operations_snapshot() -> None:
    catalog = build_catalog()
    assert [op.operation for op in catalog.operations] == [
        "fetch_units", "aggregate_metrics", "fetch_peer_candidates", "fetch_unit_context",
    ]
    assert catalog.catalog_version == "1.3.0"
    # the frozen copy the Orchestrator imports must equal what the layer generates (DEC-036)
    assert load_catalog("data") == catalog
    agg = catalog.operation("aggregate_metrics")
    assert agg.produces == ["metric_table", "dq_report"] and agg.serves == [TaskKind.LOOKUP] and agg.deadline_s == 90
    assert "avg_dom_unsold" in agg.input_schema["properties"]["metrics"]["items"]["enum"]
    ctx = catalog.operation("fetch_unit_context")
    assert ctx.requires == ["unit_set"] and ctx.input_fields == {"unit_set": "unit_set_package_id"}
    assert catalog.operation("fetch_peer_candidates").serves == []
    assert {v.name for v in catalog.vocabulary.metrics} >= {"absorption_rate", "avg_dom_unsold"}
    assert all(op.retries_transient_internally for op in catalog.operations)


def test_catalog_error_codes_classes_match_b02() -> None:
    catalog = build_catalog()
    for op in catalog.operations:
        assert op.error_codes == {code: ErrorClass(cls) for code, cls in B02_ERROR_CLASSES.items()}
