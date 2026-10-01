"""`insight_evidence@1`: the typed boundary between Insight (producer) and Chart / Report (consumers)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from vdagent_contracts.insight_evidence import (
    METRICS,
    EvidenceError,
    compare_metric_id,
    comparison_facts,
    parse_evidence,
    peer_bindings,
    peer_claims,
    same_value,
)

DATASET = {"artifact_id": "art_ds", "version": 1, "artifact_type": "dataset", "content_hash": "a" * 64}
DOM = "fact_unit_inventory_snapshot.unsold_days_dom"
DEFECT = "dm_unit_friction_diagnostics.physical_defect_penalty"
SPREAD = "dm_unit_friction_diagnostics.price_spread_vs_peer_pct"
PEERS = "dm_unit_friction_diagnostics.peer_n"
PRICE = "fact_unit_inventory_snapshot.net_price_per_m2"


def metric(metric_id: str, value: str, role: str = "primary", **over: Any) -> dict[str, Any]:
    known = METRICS.get(metric_id)
    peer = known is not None and known.peer is not None
    body = {
        "metric_id": metric_id, "slot": metric_id.rsplit(".", 1)[-1], "label": known.label if known else metric_id,
        "value_exact": value, "unit": known.unit if known else "COUNT", "role": role,
        "source_ref": f"art_ds@1#/tables/{metric_id.split('.')[0]}/0/{metric_id.split('.')[1]}",
        "chartable": not peer, "not_chartable_reason": "PEER_BASIS_COMPARE_OWNS" if peer else None,
    }
    body.update(over)
    return body


def evidence(**over: Any) -> dict[str, Any]:
    body = {
        "schema_version": "insight_evidence@2", "snapshot_id": "SNAP-1", "semantic_config_version": "3.1.0",
        "dataset_ref": dict(DATASET), "candidates_ref": {"artifact_id": "ART-INSIGHT-CANDIDATES-x", "content_hash": "b" * 64},
        "findings": [{
            "finding_id": "C-T1-100005-1-SEVERE_PHYSICAL_DEFECT", "insight_id": "INS-001", "insight_type": "ROOT_CAUSE_SIGNAL",
            "cause_code": "SEVERE_PHYSICAL_DEFECT", "level": "UNIT", "subject": {"type": "unit", "id": "100005", "label": "OCP-U00005"},
            "severity_rank": 1, "attribution_score": "0.600", "confidence": "MEDIUM",
            "metrics": [metric(DOM, "364", "context"), metric(DEFECT, "95"),
                        metric("insight_computed.overdue_units", "3", source_ref=None, chartable=False,
                               not_chartable_reason="COMPUTED_BY_INSIGHT")],
            "visual_intents": [
                {"question": "current_value", "chart_type": "kpi_card", "metric_ids": [DOM, DEFECT], "requires": None},
                {"question": "target_vs_peer", "chart_type": "bar", "metric_ids": [PRICE], "requires": "comparison"},
            ],
            "limitations": [],
        }],
    }
    body.update(over)
    return body


def finding(ev: dict[str, Any]) -> dict[str, Any]:
    return ev["findings"][0]


def code_of(payload: dict[str, Any]) -> str:
    with pytest.raises(EvidenceError) as caught:
        parse_evidence(payload)
    return caught.value.code


def test_a_valid_block_parses_with_its_typed_fields() -> None:
    ev = parse_evidence({"evidence": evidence()})
    [f] = ev.findings
    assert ev.dataset_ref.artifact_id == "art_ds" and f.subject.label == "OCP-U00005"
    assert [m.metric_id for m in f.metrics if m.chartable] == [DOM, DEFECT]


def test_a_missing_block_is_its_own_error_never_a_fallback_to_the_narrative() -> None:
    assert code_of({"insight": {"insights": []}}) == "INSIGHT_EVIDENCE_MISSING"


@pytest.mark.parametrize("mutate", [
    lambda e: e.update(schema_version="insight_evidence@0"),
    lambda e: finding(e)["metrics"][1].update(metric_id="dm_unit_friction_diagnostics.invented"),  # metric id must resolve
    lambda e: finding(e)["metrics"][1].update(unit="PCT"),  # unit must match the catalog
    lambda e: finding(e)["metrics"][1].update(label="Hiệu suất căn"),  # label must be the catalog label
    lambda e: finding(e)["metrics"][1].update(source_ref=None),  # a chartable Data value needs its pointer
    lambda e: finding(e)["metrics"][1].update(source_ref="art_other@1#/tables/x/0/y"),  # into the pinned dataset only
    lambda e: finding(e)["metrics"][1].update(value_exact="n/a"),
    lambda e: finding(e)["metrics"][1].update(value_exact="NaN"),
    lambda e: finding(e)["metrics"].append(metric(SPREAD, "12.38")),  # a mart peer figure: Compare owns peer facts
    lambda e: finding(e)["metrics"].append(metric(PEERS, "7", "supporting")),
    lambda e: finding(e)["metrics"][1].update(chartable=False, not_chartable_reason=None),  # a skip must say why
    lambda e: finding(e)["visual_intents"][0].update(metric_ids=[DOM, "insight_computed.overdue_units"]),  # not chartable
    lambda e: finding(e)["visual_intents"][0].update(metric_ids=[DOM, "fact_unit_inventory_snapshot.absent"]),
    lambda e: finding(e)["visual_intents"][0].update(chart_type="pie"),  # unsupported for a single value
    lambda e: finding(e)["visual_intents"][1].update(requires=None),  # a peer view needs Compare
    lambda e: finding(e)["metrics"].append(metric(DOM, "364", "context")),  # one metric once per finding
    lambda e: e["findings"].append(copy.deepcopy(finding(e))),  # finding ids are unique
    lambda e: e["dataset_ref"].update(content_hash=None),
])
def test_contract_violations_are_rejected_deterministically(mutate: Any) -> None:
    ev = evidence()
    mutate(ev)
    assert code_of({"evidence": ev}) == "INSIGHT_EVIDENCE_INVALID"
    assert code_of({"evidence": ev}) == "INSIGHT_EVIDENCE_INVALID"  # same input, same error


def test_the_error_names_where_the_contract_was_broken() -> None:
    ev = evidence()
    finding(ev)["metrics"][1]["unit"] = "PCT"
    with pytest.raises(EvidenceError) as caught:
        parse_evidence({"evidence": ev})
    assert "findings.0.metrics.1" in caught.value.message


def test_a_finding_without_a_chartable_value_is_valid_and_simply_has_no_visual_intent() -> None:
    ev = evidence()
    finding(ev).update(metrics=[metric("insight_computed.overdue_units", "3", source_ref=None, chartable=False,
                                       not_chartable_reason="COMPUTED_BY_INSIGHT")], visual_intents=[])
    assert parse_evidence({"evidence": ev}).findings[0].visual_intents == []


def test_every_catalog_metric_has_a_label_and_a_unit_and_peer_metrics_name_a_compare_counterpart() -> None:
    for metric_id, definition in METRICS.items():
        table, _, field = metric_id.partition(".")
        assert table and field and definition.label and definition.unit
        if definition.peer is not None:
            assert definition.peer.compare_metric in METRICS and definition.peer.field.startswith("/")


def compare_row(metric_id: str, **fields: Any) -> dict[str, Any]:
    table, column = metric_id.split(".")
    return {"metric": "x", "sourceRef": {"table": table, "columns": [column]}, **fields}


def test_compare_rows_are_identified_by_the_dataset_field_they_read() -> None:
    assert compare_metric_id(compare_row(PRICE)) == PRICE
    assert compare_metric_id({"metric": "dom"}) is None


COMPARISON = {
    "artifact_id": "art_cmp", "version": 1,
    "input_artifact_refs": [{"artifact_id": "art_ds", "version": 1, "artifact_type": "dataset", "content_hash": "a" * 64},
                            {"artifact_id": "art_pd", "version": 2, "artifact_type": "peer_definition", "content_hash": "c" * 64}],
    "snapshot_refs": ["SNAP-1"], "semantic_config_version": "3.1.0",
    "payload": {"metrics": [
        compare_row(PRICE, metric="net_asking_price_per_m2", subjectValue=82953095, unit="VND/m2", absGap=7261313,
                    pctGap="9.59", benchmark={"n": 5, "stat": "median", "value": 75691782}),
        compare_row(DOM, metric="dom", subjectValue=364, unit="days", absGap=71, pctGap="24.23",
                    benchmark={"n": 5, "stat": "median", "value": 293}),
        {"metric": "discount_pct", "subjectValue": None, "benchmark": {"value": None, "n": 5}},  # no sourceRef: skipped
    ]},
}


def test_comparison_facts_are_read_from_compare_with_exact_pointers_never_recomputed() -> None:
    facts = comparison_facts(COMPARISON)
    assert set(facts) == {PRICE, DOM}
    price = facts[PRICE]
    assert (price.comparison_id, price.metric, price.subject_value, price.peer_value, price.peer_stat) == (
        "art_cmp@1", "net_asking_price_per_m2", "82953095", "75691782", "median")
    assert (price.delta, price.delta_pct, price.peer_count, price.peer_definition) == ("7261313", "9.59", 5, "art_pd@2")
    assert price.refs == {"subject_value": "art_cmp@1#/metrics/0/subjectValue", "peer_value": "art_cmp@1#/metrics/0/benchmark/value",
                          "delta_pct": "art_cmp@1#/metrics/0/pctGap", "peer_count": "art_cmp@1#/metrics/0/benchmark/n"}
    assert (price.snapshot_id, price.semantic_config_version) == ("SNAP-1", "3.1.0")


def test_a_narrated_peer_number_is_detected_as_not_insights_to_state() -> None:
    insight = {"insight": {"insights": [
        {"insight_id": "INS-001", "claim": {"numeric_bindings": [
            {"slot": "dom", "value": "138", "metric_ref": "art_x~insight#/fact_unit_inventory_snapshot/0/unsold_days_dom"},
            {"slot": "spread", "value": "12.40", "metric_ref": "art_x~insight#/dm_unit_friction_diagnostics/0/price_spread_vs_peer_pct"}]}},
        {"insight_id": "INS-002", "claim": {"numeric_bindings": [
            {"slot": "peers", "value": "7", "metric_ref": "art_x~insight#/dm_unit_friction_diagnostics/0/peer_count"}]}},
        {"insight_id": "INS-003", "claim": {"numeric_bindings": []}},
    ]}}
    assert peer_claims(insight) == [("INS-001", "spread", "12.40"), ("INS-002", "peers", "7")]
    assert peer_claims({"insight": {"insights": []}}) == []


def test_values_are_compared_exactly_as_decimals() -> None:
    assert same_value("12.40", "12.4") and same_value(364, "364") and same_value("0.10", 0.1)
    assert not same_value("12.38", "9.59") and not same_value(None, "1") and not same_value("n/a", "n/a")


def test_a_finding_needing_a_peer_view_is_bound_to_compares_fact_by_metric_id() -> None:
    insight = {"payload": {"evidence": evidence()}}
    [binding] = peer_bindings(insight, COMPARISON)["INS-001"]
    assert (binding.finding_id, binding.metric_id) == ("C-T1-100005-1-SEVERE_PHYSICAL_DEFECT", PRICE)
    assert binding.fact is not None and (binding.fact.delta_pct, binding.fact.peer_count) == ("9.59", 5)
    [unbound] = peer_bindings(insight, None)["INS-001"]  # no comparison in the run: required, not invented
    assert unbound.fact is None
    assert peer_bindings({"payload": {}}, COMPARISON) == {}  # no evidence block: nothing to bind
