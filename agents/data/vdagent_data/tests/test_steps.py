"""WS2: deterministic StepSpec operations over the real-estate DW (docs/integration/AGENT_CONTRACT_MATRIX.md §3.1).

Every test runs against a freshly built `re_warehouse` and the Backend's real MCP tools; no LLM is involved.
"""

from __future__ import annotations

import json

import shutil
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from vdagent_data.tests.conftest import ALICE, BOB, McpPort
from vdagent_backend.mcp.tools import McpTools
from vdagent_backend.tokens import McpIdentity
from vdagent_contracts.canonical import percentile_inc
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_data.steps import DATA_ERROR_CLASSES, run_step

GOLDEN_SNAPSHOT, GOLDEN_SEMANTIC = "SNAP-2026-09-28", "sc-1"
HERO_KEY = "U-PRJ-X-A12-08"
GOLDEN_PEERS = ["A12-11", "A10-02", "A14-03", "A06-01", "B09-05", "B11-07", "B15-02"]  # backend/tests/test_re_fixtures.py:18


def step(operation: str = "fetch_units", spec: dict[str, Any] | None = None, **overrides: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": f"t_{ALICE}",
        "plan_id": "pl_ws2",
        "step_id": "B1",
        "idempotency_key": "pl_ws2:B1",
        "operation": operation,
        "spec": spec if spec is not None else {"subject_unit_code": "A12-08", "population": "peer_candidates"},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X"], "zone_ids": []}},
        "snapshot_id": GOLDEN_SNAPSHOT,
        "semantic_config_version": GOLDEN_SEMANTIC,
        "original_question": "Vì sao căn A12-08 bán chậm?",
    }
    fields.update(overrides)
    return StepSpec.model_validate(fields)


async def artifacts_of(port: McpPort, report: AgentReport) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ref in report.artifact_refs:
        out[ref.artifact_type.value] = await port.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})
    return out


def metric(metrics: dict[str, Any], metric_id: str, subject_id: str = HERO_KEY) -> dict[str, Any]:
    [row] = [m for m in metrics["payload"]["metrics"] if m["metric_id"] == metric_id and m["subject"]["id"] == subject_id]
    return row


async def listed(port: McpPort) -> list[dict[str, Any]]:
    return (await port.call("artifact_list", {}))["artifacts"]


# ---- golden A12-08 (E2E_TEST_PLAN.md §3, boundary E-02/E-03) -------------------------------------------------------


async def test_golden_a12_08_fetch_units(alice: McpPort) -> None:
    report = await run_step(step(), alice)

    assert report.state == "completed" and report.error is None
    assert report.snapshot_id == GOLDEN_SNAPSHOT and report.semantic_config_version == GOLDEN_SEMANTIC
    assert sorted(r.artifact_type.value for r in report.artifact_refs) == ["dataset", "dq", "metric"]
    arts = await artifacts_of(alice, report)
    for art in arts.values():
        assert art["snapshot_refs"] == [GOLDEN_SNAPSHOT]
        assert art["semantic_config_version"] == GOLDEN_SEMANTIC
        assert art["producer"]["agent"] == "data"
        assert art["artifact_id"].startswith("art_") and art["version"] == 1 and len(art["content_hash"]) == 64
    dataset, metrics, dq = arts["dataset"], arts["metric"], arts["dq"]
    assert (dataset["schema_version"], metrics["schema_version"], dq["schema_version"]) == ("re_dataset@1", "re_metric@1", "re_dq@1")

    tables = dataset["payload"]["tables"]
    [hero] = [u for u in tables["dim_unit_master"] if u["unit_code"] == "A12-08"]
    assert hero["unit_key"] == HERO_KEY and hero["net_area_m2"] == "63.02"
    [inv] = [r for r in tables["fact_unit_inventory_snapshot"] if r["unit_key"] == HERO_KEY]
    assert (inv["snapshot_date_key"], inv["inventory_status"], inv["unsold_days_dom"], inv["net_price_per_m2"]) == (
        20260928, "AVAILABLE", 138, 72500000,
    )
    assert {r["snapshot_date_key"] for r in tables["fact_unit_inventory_snapshot"]} == {20260928}  # never 20260929
    channels = {c["channel_key"]: c for c in tables["dim_sales_channel"]}  # WS3: commission inputs for Insight
    assert inv["channel_key"] in channels and set(channels) == {r["channel_key"] for r in tables["fact_unit_inventory_snapshot"]}
    assert isinstance(channels[inv["channel_key"]]["base_commission_pct"], str)

    assert metric(metrics, "dom_days")["value"] == 138
    assert metric(metrics, "net_price_per_m2_vnd")["value"] == 72500000
    assert metric(metrics, "net_area_m2")["value"] == "63.02" and metric(metrics, "net_area_m2")["unit"] == "M2"
    assert metric(metrics, "dw_peer_n")["value"] == 7  # dm_unit_friction_diagnostics.peer_n (canonical DW count)

    codes = {u["unit_code"] for u in tables["dim_unit_master"]}
    assert set(GOLDEN_PEERS) <= codes  # every canonical peer is in the candidate population
    assert "D12-09" not in codes and all(u["project_key"] == "PRJ-X" for u in tables["dim_unit_master"])
    # WS7 F-08: nothing about out-of-scope rows (not even how many there are) is stored in the artifact
    assert "hidden_rows" not in dataset["payload"] and "hidden" not in json.dumps(dataset["payload"]["queries"])


async def test_golden_missing_metrics_are_null_with_limitations(alice: McpPort) -> None:
    report = await run_step(step(), alice)
    arts = await artifacts_of(alice, report)
    metrics = arts["metric"]
    leads = metric(metrics, "inquiry_leads_30d")
    assert leads["value"] is None  # A12-08 has no funnel rows and the table covers 3 days, never 0
    assert metric(metrics, "discount_pct")["value"] is None  # no DW source: null, never 0 (D8)
    assert metrics["status"] == "PARTIAL"
    assert "WINDOW_INCOMPLETE:inquiry_leads_30d:3" in metrics["limitations"]
    assert "METRIC_UNAVAILABLE:discount_pct" in metrics["limitations"]
    assert report.partial is True and "WINDOW_INCOMPLETE:inquiry_leads_30d:3" in report.warnings
    dq = arts["dq"]["payload"]
    assert dq["coverage"]["fact_sales_funnel_daily"] == {
        "min_date_key": 20260925, "max_date_key": 20260927, "days_covered": 3, "days_required": 30, "complete": False,
    }


async def test_golden_blocked_semantics_are_surfaced_not_defaulted(alice: McpPort) -> None:
    arts = await artifacts_of(alice, await run_step(step(), alice))
    dataset = arts["dataset"]
    config = dataset["payload"]["semantic_config"]
    assert config["peer_area_tolerance_pct"] == {"value": "0.10", "status": "APPROVED", "ratio": "0.10"}
    assert config["min_group_size"] == {"value": 5, "status": "PENDING"}
    assert "min_peer_count" not in config
    for code in ("CONFIG_PENDING:min_group_size", "BLOCKED:D2b_segment_mapping", "SYNTHETIC_SOURCE:net_area_m2"):
        assert code in dataset["limitations"]
    [project] = dataset["payload"]["tables"]["dim_project_profile"]
    assert project["segment"] == "HIGH_END"  # raw DW value kept; no Insight enum mapping (D2b)


async def test_lineage_refs_and_hashes_resolve(alice: McpPort) -> None:
    report = await run_step(step(), alice)
    arts = await artifacts_of(alice, report)
    dataset = arts["dataset"]
    for kind in ("metric", "dq"):
        [ref] = arts[kind]["input_artifact_refs"]
        assert ref == {"artifact_id": dataset["artifact_id"], "version": 1, "artifact_type": "dataset",
                       "content_hash": dataset["content_hash"]}
    assert dataset["input_artifact_refs"] == []
    assert "re:dim_unit_master" in dataset["source_refs"] and "re:snapshot_manifest" in dataset["source_refs"]
    assert all(q["sql_sha256"] and len(q["sql_sha256"]) == 64 for q in dataset["payload"]["queries"])
    for ref in report.artifact_refs:
        assert ref.content_hash == arts[ref.artifact_type.value]["content_hash"]


async def test_decimals_travel_as_strings(alice: McpPort) -> None:
    arts = await artifacts_of(alice, await run_step(step(), alice))
    for row in arts["dataset"]["payload"]["tables"]["dim_unit_master"]:
        assert isinstance(row["net_area_m2"], str) and isinstance(row["area_m2"], str)
    assert not _floats(arts)


def _floats(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_floats(v) for v in value.values())
    if isinstance(value, list):
        return any(_floats(v) for v in value)
    return False


async def test_subject_population_holds_only_the_subject(alice: McpPort) -> None:
    report = await run_step(step(spec={"subject_unit_code": "A12-08", "population": "subject"}), alice)
    arts = await artifacts_of(alice, report)
    assert [u["unit_code"] for u in arts["dataset"]["payload"]["tables"]["dim_unit_master"]] == ["A12-08"]


# ---- snapshot and semantic enforcement ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshot", "semantic", "code"),
    [
        (None, GOLDEN_SEMANTIC, "SNAPSHOT_REQUIRED"),
        ("SNAP-2026-09-29", GOLDEN_SEMANTIC, "SNAPSHOT_NOT_APPROVED"),  # DRAFT: never substituted
        ("SNAP-2099-01-01", GOLDEN_SEMANTIC, "SNAPSHOT_UNKNOWN"),
        ("latest", GOLDEN_SEMANTIC, "SNAPSHOT_UNKNOWN"),
        (GOLDEN_SNAPSHOT, None, "SEMANTIC_VERSION_REQUIRED"),
        (GOLDEN_SNAPSHOT, "3.1.0", "SEMANTIC_VERSION_MISMATCH"),
    ],
)
async def test_snapshot_and_semantic_are_enforced(alice: McpPort, snapshot: str | None, semantic: str | None, code: str) -> None:
    report = await run_step(step(snapshot_id=snapshot, semantic_config_version=semantic), alice)
    assert report.state == "rejected" and report.error is not None
    assert report.error.code == code and DATA_ERROR_CLASSES[code] is ErrorClass.SPEC_ISSUE
    assert report.artifact_refs == [] and await listed(alice) == []


async def test_older_approved_snapshot_is_served_as_requested(alice: McpPort) -> None:
    report = await run_step(step(snapshot_id="SNAP-2026-08-31"), alice)
    arts = await artifacts_of(alice, report)
    assert metric(arts["metric"], "dom_days")["value"] == 110  # the requested snapshot, not the latest
    assert arts["dataset"]["snapshot_refs"] == ["SNAP-2026-08-31"]


# ---- authorization --------------------------------------------------------------------------------------------------


async def test_unit_outside_scope_is_not_found(alice: McpPort) -> None:
    report = await run_step(step(spec={"subject_unit_code": "D12-09", "population": "subject"}), alice)
    assert report.state == "failed" and report.error is not None and report.error.code == "UNIT_NOT_FOUND"
    assert DATA_ERROR_CLASSES["UNIT_NOT_FOUND"] is ErrorClass.NO_DATA
    assert "PRJ-Y" not in report.error.message  # nothing about the hidden row leaks
    assert await listed(alice) == []


async def test_other_user_cannot_reach_prj_x(alice: McpPort) -> None:
    bob = alice.as_user(BOB)
    spec = step(user_context={"user_id": BOB, "authorized_scope": {"project_ids": ["PRJ-Y"], "zone_ids": []}})
    report = await run_step(spec, bob)
    assert report.state == "failed" and report.error is not None and report.error.code == "UNIT_NOT_FOUND"


async def test_user_context_must_match_the_caller(alice: McpPort) -> None:
    report = await run_step(step(user_context={"user_id": BOB, "authorized_scope": {"project_ids": ["PRJ-X"]}}), alice)
    assert report.state == "rejected" and report.error is not None and report.error.code == "USER_CONTEXT_MISMATCH"
    assert DATA_ERROR_CLASSES["USER_CONTEXT_MISMATCH"] is ErrorClass.NO_ACCESS


async def test_scope_comes_from_the_backend_not_the_step(alice: McpPort) -> None:
    widened = step(user_context={"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X", "PRJ-Y"]}})
    arts = await artifacts_of(alice, await run_step(widened, alice))
    assert {u["project_key"] for u in arts["dataset"]["payload"]["tables"]["dim_unit_master"]} == {"PRJ-X"}


# ---- spec validation ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operation", "spec", "code"),
    [
        ("drop_tables", {}, "UNKNOWN_OPERATION"),
        ("fetch_units", {}, "INVALID_SPEC"),
        ("fetch_units", {"subject_unit_code": "A12-08", "population": "everything"}, "INVALID_SPEC"),
        ("fetch_units", {"subject_unit_code": "A12-08'; --", "population": "subject"}, "INVALID_SPEC"),
        ("aggregate_metrics", {"metrics": ["dom_days", "foo"], "group_by": ["zone_key"]}, "UNKNOWN_METRIC"),
        ("aggregate_metrics", {"metrics": ["dom_days"], "group_by": ["unit_key; DROP"]}, "INVALID_SPEC"),
    ],
)
async def test_invalid_specs_are_rejected(alice: McpPort, operation: str, spec: dict[str, Any], code: str) -> None:
    report = await run_step(step(operation, spec), alice)
    assert report.state == "rejected" and report.error is not None and report.error.code == code
    assert DATA_ERROR_CLASSES[code] is ErrorClass.SPEC_ISSUE
    assert await listed(alice) == []


# ---- net_area_m2 (D9) -----------------------------------------------------------------------------------------------


@pytest.fixture
def tampered(tmp_path: Path, re_db: str, mcp_tools: McpTools) -> Any:
    """A copy of the DW with chosen `net_area_m2` values overwritten (the DDL forbids NULL; '' and 'n/a' stand in)."""

    def make(values: dict[str, str]) -> McpPort:
        path = str(tmp_path / "re_tampered.db")
        shutil.copy(re_db, path)
        with sqlite3.connect(path) as conn:
            for code, value in values.items():
                conn.execute("UPDATE dim_unit_master SET net_area_m2 = ? WHERE unit_code = ? AND project_key = 'PRJ-X'", (value, code))
        conn.close()
        mcp_tools._re_warehouse_db = path  # pyright: ignore[reportPrivateUsage]
        return McpPort(mcp_tools, McpIdentity(user_id=ALICE, agent="data", invocation_id=f"inv_{ALICE}", task_id=f"t_{ALICE}"))

    return make


@pytest.mark.parametrize("value", ["", "n/a", "0"])
async def test_subject_without_net_area_fails_without_fallback(tampered: Any, value: str) -> None:
    port = tampered({"A12-08": value})
    report = await run_step(step(), port)
    assert report.state == "failed" and report.error is not None and report.error.code == "SUBJECT_AREA_UNAVAILABLE"
    assert DATA_ERROR_CLASSES["SUBJECT_AREA_UNAVAILABLE"] is ErrorClass.DATA_QUALITY
    assert await listed(port) == []


async def test_candidate_without_net_area_is_excluded_with_limitation(tampered: Any) -> None:
    port = tampered({"A12-11": "n/a"})
    report = await run_step(step(), port)
    arts = await artifacts_of(port, report)
    codes = {u["unit_code"] for u in arts["dataset"]["payload"]["tables"]["dim_unit_master"]}
    assert "A12-11" not in codes and "A10-02" in codes
    assert "PEER_AREA_UNAVAILABLE:1" in arts["dataset"]["limitations"]
    assert arts["dataset"]["payload"]["excluded"] == [{"unit_code": "A12-11", "reason": "net_area_unavailable"}]
    [field] = [f for f in arts["dq"]["payload"]["fields"] if f["field"] == "net_area_m2"]
    assert field["missing_count"] == 1


# ---- aggregate_metrics ----------------------------------------------------------------------------------------------


async def test_aggregate_metrics_by_zone_matches_an_independent_computation(alice: McpPort, re_db: str) -> None:
    spec = {"metrics": ["dom_days", "net_price_per_m2_vnd", "discount_pct"], "group_by": ["zone_key"],
            "filters": {"unit_type": "2PN", "inventory_status": "AVAILABLE"}}
    report = await run_step(step("aggregate_metrics", spec), alice)
    arts = await artifacts_of(alice, report)
    rows = arts["metric"]["payload"]["metrics"]

    with sqlite3.connect(re_db) as conn:
        doms = [Decimal(r[0]) for r in conn.execute(
            "SELECT i.unsold_days_dom FROM fact_unit_inventory_snapshot i JOIN dim_unit_master u USING (unit_key)"
            " WHERE i.snapshot_date_key = 20260928 AND u.project_key = 'PRJ-X' AND u.zone_key = 'ZN-A'"
            " AND u.unit_type = '2PN' AND i.inventory_status = 'AVAILABLE'")]
    conn.close()
    [zn_a] = [r for r in rows if r["metric_id"] == "dom_days" and r["subject"] == {"type": "GROUP", "id": "zone_key=ZN-A", "label": "ZN-A"}]
    assert zn_a["n"] == len(doms) and zn_a["value"] == str(percentile_inc(doms, Decimal("0.5")))
    assert zn_a["statistic"] == "median"
    assert {r["subject"]["id"] for r in rows} <= {f"zone_key={z}" for z in ("ZN-A", "ZN-B", "ZN-C")}  # PRJ-X zones only
    assert all(r["value"] is None for r in rows if r["metric_id"] == "discount_pct")
    assert "METRIC_UNAVAILABLE:discount_pct" in arts["metric"]["limitations"]
    assert not _floats(arts)
