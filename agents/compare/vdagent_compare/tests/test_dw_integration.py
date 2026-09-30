"""WS3: Compare consumes the canonical Data artifacts (re_dataset@1 / re_metric@1 / re_dq@1) of the real-estate DW."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from vdagent_compare import vh_data
from vdagent_compare.stepspec import run_step
from vdagent_contracts.canonical import percentile_inc
from vdagent_contracts.messages import StepSpec
from vdagent_data.steps import run_step as run_data_step
from vdagent_data.tests.conftest import ALICE, McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_data.tests.test_steps import GOLDEN_PEERS, step as data_step

HERO = "U-PRJ-X-A12-08"


@pytest.fixture
def no_fixture_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """The integrated path must never load the hero fixture or a CSV pack."""

    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("legacy data pack loaded on the integrated path")

    from vdagent_compare import vh_service

    for name in ("load_hero_package", "load_csv_package", "load_package_for"):
        monkeypatch.setattr(vh_data, name, refuse)
        if hasattr(vh_service, name):
            monkeypatch.setattr(vh_service, name, refuse)


async def data_refs(port: McpPort, **over: Any) -> list[dict[str, Any]]:
    report = await run_data_step(data_step(**over), port)
    assert report.state == "completed"
    return [r.model_dump(mode="json") for r in report.artifact_refs]


def compare_step(refs: list[dict[str, Any]], **over: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": f"t_{ALICE}", "plan_id": "pl_ws3", "step_id": "B3", "idempotency_key": "pl_ws3:B3",
        "operation": "compare_to_peers",
        "spec": {"subject": {"entityType": "unit", "entityCode": "A12-08"}, "comparisonMode": "peer_group"},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X"], "zone_ids": []}},
        "snapshot_id": "SNAP-2026-09-28", "semantic_config_version": "sc-1",
        "input_refs": refs, "original_question": "Vì sao căn A12-08 bán chậm?",
    }
    fields.update(over)
    return StepSpec.model_validate(fields)


async def outputs(port: McpPort, refs: list[dict[str, Any]]) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    report = await run_step(compare_step(refs), port.as_agent("compare"))
    assert report.state == "completed", report
    arts = {r.artifact_type.value: await port.call("artifact_get", {"artifact_id": r.artifact_id, "version": r.version})
            for r in report.artifact_refs}
    dataset = await port.call("artifact_get", {"artifact_id": refs[0]["artifact_id"]})
    return report, arts["peer_definition"], arts["comparison"], dataset


def _row(comparison: dict[str, Any], metric: str) -> dict[str, Any]:
    [row] = [m for m in comparison["payload"]["metrics"] if m["metric"] == metric]
    return row


async def test_golden_comparison_from_the_canonical_dataset(alice: McpPort, no_fixture_pack: None) -> None:
    refs = await data_refs(alice)
    report, peer_def, comparison, dataset = await outputs(alice, refs)

    for art in (peer_def, comparison):
        assert art["producer"]["agent"] == "compare"
        assert art["snapshot_refs"] == ["SNAP-2026-09-28"] and art["semantic_config_version"] == "sc-1"
        assert art["input_artifact_refs"][:3] == refs  # the exact Data dataset/metric/dq, pinned by hash
    assert (peer_def["schema_version"], comparison["schema_version"]) == ("peer_definition@1", "comparison@1")
    assert comparison["input_artifact_refs"][3] == {"artifact_id": peer_def["artifact_id"], "version": 1,
                                                    "artifact_type": "peer_definition", "content_hash": peer_def["content_hash"]}
    assert comparison["payload"]["subject"]["entityId"] == HERO
    assert Decimal(str(_row(comparison, "dom")["subjectValue"])) == 138
    assert Decimal(str(_row(comparison, "net_asking_price_per_m2")["subjectValue"])) == 72500000


async def test_peers_use_net_area_and_the_ratio_tolerance(alice: McpPort) -> None:
    refs = await data_refs(alice)
    _, peer_def, _, dataset = await outputs(alice, refs)
    payload = peer_def["payload"]
    assert payload["subjectProfile"]["areaM2"] == "63.02"  # net_area_m2 (D9), never area_m2 68.50
    assert payload["areaTolerance"] == {"ratio": "0.10", "percent": "10.00",
                                         "source": "semantic_config[sc-1].peer_area_tolerance_pct"}
    units = {u["unit_key"]: u for u in dataset["payload"]["tables"]["dim_unit_master"]}
    for peer in payload["peers"]:
        assert peer["entityId"].startswith("U-PRJ-X-")  # canonical TEXT keys, PRJ-X only
        assert abs(Decimal(units[peer["entityId"]]["net_area_m2"]) - Decimal("63.02")) <= Decimal("6.302")


async def test_benchmark_is_the_median_of_the_selected_peers(alice: McpPort) -> None:
    refs = await data_refs(alice)
    _, peer_def, comparison, dataset = await outputs(alice, refs)
    inventory = {r["unit_key"]: r for r in dataset["payload"]["tables"]["fact_unit_inventory_snapshot"]}
    peers = [p["entityId"] for p in peer_def["payload"]["peers"]]
    doms = [Decimal(inventory[p]["unsold_days_dom"]) for p in peers]
    prices = [Decimal(inventory[p]["net_price_per_m2"]) for p in peers]
    for metric, values in (("dom", doms), ("net_asking_price_per_m2", prices)):
        benchmark = _row(comparison, metric)["benchmark"]
        assert benchmark["stat"] == "median" and benchmark["n"] == len(peers)
        assert Decimal(str(benchmark["value"])) == percentile_inc(values, Decimal("0.5"))
    assert _row(comparison, "dom")["sourceRef"]["artifactId"] == refs[0]["artifact_id"]


async def test_missing_metrics_stay_null_with_limitations(alice: McpPort) -> None:
    refs = await data_refs(alice)
    report, _, comparison, _ = await outputs(alice, refs)
    for metric in ("discount_pct", "inquiry_leads_30d"):
        rows = [m for m in comparison["payload"]["metrics"] if m["metric"] == metric]
        assert all(r["subjectValue"] is None for r in rows)  # absent or null, never 0
    for code in ("METRIC_UNAVAILABLE:discount_pct", "WINDOW_INCOMPLETE:inquiry_leads_30d:3",
                 "BLOCKED:B-2_min_peer_count"):
        assert code in comparison["limitations"]
    assert report.partial is True


@pytest.mark.skip(reason="B-11 BLOCKED: no approved rule reproduces the 7 golden peers; see INTEGRATION_MASTER_PLAN B-11")
async def test_golden_peer_set_is_the_seven_canonical_peers(alice: McpPort) -> None:
    _, peer_def, _, _ = await outputs(alice, await data_refs(alice))
    assert sorted(p["entityCode"] for p in peer_def["payload"]["peers"]) == sorted(GOLDEN_PEERS)


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"snapshot_id": "SNAP-2026-08-31"}, "SNAPSHOT_MISMATCH"),
        ({"semantic_config_version": "3.1.0"}, "SEMANTIC_VERSION_MISMATCH"),
        ({"operation": "draw_chart"}, "UNKNOWN_OPERATION"),
        ({"spec": {"comparisonMode": "peer_group"}}, "INVALID_SPEC"),
    ],
)
async def test_mismatches_are_rejected(alice: McpPort, over: dict[str, Any], code: str) -> None:
    report = await run_step(compare_step(await data_refs(alice), **over), alice.as_agent("compare"))
    assert report.state == "rejected" and report.error is not None and report.error.code == code
    kinds = {a["artifact_type"] for a in (await alice.call("artifact_list", {}))["artifacts"]}
    assert not kinds & {"comparison", "peer_definition"}


async def test_invalid_ref_is_rejected(alice: McpPort) -> None:
    refs = await data_refs(alice)
    refs[1] = {**refs[1], "artifact_id": "art_missing"}
    report = await run_step(compare_step(refs), alice.as_agent("compare"))
    assert report.error is not None and report.error.code == "INPUT_NOT_FOUND"


async def test_out_of_scope_subject_is_not_found(alice: McpPort) -> None:
    refs = await data_refs(alice)
    spec = {"subject": {"entityType": "unit", "entityCode": "D12-09"}, "comparisonMode": "peer_group"}
    report = await run_step(compare_step(refs, spec=spec), alice.as_agent("compare"))
    assert report.state == "failed" and report.error is not None and report.error.code == "SUBJECT_NOT_FOUND"


def test_standalone_hero_fixture_mode_is_unchanged(tmp_path: Path) -> None:
    from vdagent_compare.vh_chat import parse_request
    from vdagent_compare.vh_service import CompareService

    result = CompareService(root=tmp_path).run(parse_request("so sánh căn A12-08 với nhóm tương đồng"))
    assert result["comparison"]["status"] == "VALID"
    assert result["comparison"]["snapshot_refs"] == ["SNAP-20260630-01"]  # the hero fixture, as before WS3
