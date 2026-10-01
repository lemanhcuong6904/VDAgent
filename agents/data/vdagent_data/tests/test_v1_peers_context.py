"""fetch_peer_candidates (the six criteria of SPEC §3.4) and fetch_unit_context (SPEC §6.3), as contract-v1.0 operations.

The expected peers and rows are computed here from the mock DW with independent Python/SQL, never taken from the agent.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.core import McpIdentity
from vdagent_data.tests.conftest import ALICE, McpPort
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_data.tests.test_v1_steps import artifacts_of, ent, listed, truth, v1
from vdagent_data.v1 import V1Result, run_step_v1

ORIENTATION = {"S": "COOL", "SE": "COOL", "E": "COOL", "W": "HOT", "SW": "HOT", "NW": "HOT", "N": "NORTH", "NE": "NORTH"}
BANDS = ["LOW", "MID", "HIGH", "TOP"]
TARGET = "A12-08"


@pytest.fixture
def edited(tmp_path: Path, re_db: str, mcp_tools: McpTools) -> Callable[..., McpPort]:
    def make(*statements: str) -> McpPort:
        path = str(tmp_path / "re_edited.db")
        shutil.copy(re_db, path)
        with sqlite3.connect(path) as conn:
            for sql in statements:
                conn.execute(sql)
        conn.close()
        mcp_tools.use_re_warehouse(path)
        return McpPort(mcp_tools, McpIdentity(user_id=ALICE, agent="data", invocation_id=f"inv_{ALICE}", task_id=f"t_{ALICE}"))
    return make


def min_peers(n: int, status: str = "APPROVED") -> str:
    return f"INSERT INTO semantic_config (config_version, config_key, config_value, status, description) VALUES ('sc-1', 'min_peer_count', '{n}', '{status}', 't')"


def expected_peers(re_db: str, code: str, bands: list[str]) -> set[str]:
    with sqlite3.connect(re_db) as conn:
        conn.row_factory = sqlite3.Row
        t = conn.execute("SELECT * FROM dim_unit_master WHERE unit_code = ?", (code,)).fetchone()
        area = Decimal(t["net_area_m2"])
        rows = conn.execute("SELECT * FROM dim_unit_master WHERE project_key = ? AND unit_key <> ?", (t["project_key"], t["unit_key"])).fetchall()
    return {u["unit_code"] for u in rows
            if u["launch_batch_id"] == t["launch_batch_id"] and u["unit_type"] == t["unit_type"] and u["floor_band"] in bands
            and abs(Decimal(u["net_area_m2"]) - area) <= Decimal("0.10") * area
            and ORIENTATION[u["balcony_orientation"]] == ORIENTATION[t["balcony_orientation"]]}


async def peer_set(port: McpPort, r: V1Result) -> dict[str, Any]:
    return (await artifacts_of(port, r))["dataset"]["payload"]


def peers_step(code: str = TARGET, **over: Any) -> Any:
    return v1("fetch_peer_candidates", {"entities": [ent(code, "UNIT")]}, question=f"So sánh căn {code} với các căn tương đồng", **over)


# ---- fetch_peer_candidates --------------------------------------------------------------------------------------------------


async def test_the_strict_peers_meet_all_six_criteria(edited: Callable[..., McpPort], re_db: str) -> None:
    port = edited(min_peers(5))
    r = await run_step_v1(peers_step(), port)
    assert r.report.state == "completed", r.report.error
    payload = await peer_set(port, r)
    strict = {c["unit_code"] for c in payload["peer_set"]["candidates"] if c["match_tier"] == "strict"}
    assert strict == expected_peers(re_db, TARGET, ["MID"]) and len(strict) >= 5
    assert TARGET not in {c["unit_code"] for c in payload["peer_set"]["candidates"]}
    assert payload["peer_set"]["is_peer_sample_constrained"] is False and payload["peer_set"]["target_unit_key"] == "U-PRJ-X-A12-08"
    assert payload["peer_set"]["min_peer_count"] == 5 and payload["peer_set"]["area_tolerance_ratio"] == "0.10"
    assert payload["population"]["subject_unit_key"] == "U-PRJ-X-A12-08" and payload["population"]["rule"] == "peer_candidates"
    assert "SMALL_SAMPLE" not in " ".join(r.report.warnings)


async def test_every_candidate_carries_its_inventory_status_and_its_rows(edited: Callable[..., McpPort]) -> None:
    port = edited(min_peers(5))
    payload = await peer_set(port, await run_step_v1(peers_step(), port))
    codes = {c["unit_code"]: c for c in payload["peer_set"]["candidates"]}
    assert all(c["inventory_status"] in ("AVAILABLE", "BOOKED", "SOLD") for c in codes.values())
    tables = payload["tables"]
    assert {u["unit_code"] for u in tables["dim_unit_master"]} == set(codes) | {TARGET}
    assert {i["unit_key"] for i in tables["fact_unit_inventory_snapshot"]} == {u["unit_key"] for u in tables["dim_unit_master"]}


async def test_too_few_peers_opens_the_adjacent_floor_bands_and_marks_them_expanded(edited: Callable[..., McpPort], re_db: str) -> None:
    strict = expected_peers(re_db, TARGET, ["MID"])
    wider = expected_peers(re_db, TARGET, ["LOW", "MID", "HIGH"])
    assert len(wider) > len(strict)
    port = edited(min_peers(len(strict) + 1))
    r = await run_step_v1(peers_step(), port)
    candidates = (await peer_set(port, r))["peer_set"]["candidates"]
    assert {c["unit_code"] for c in candidates} == wider
    assert {c["unit_code"] for c in candidates if c["match_tier"] == "strict"} == strict
    assert {c["match_tier"] for c in candidates if c["unit_code"] in wider - strict} == {"expanded"}


async def test_a_sample_still_below_the_minimum_is_flagged_not_hidden(edited: Callable[..., McpPort], re_db: str) -> None:
    port = edited(min_peers(500))
    r = await run_step_v1(peers_step(), port)
    assert r.report.state == "completed", r.report.error
    payload = await peer_set(port, r)
    n = len(payload["peer_set"]["candidates"])
    assert payload["peer_set"]["is_peer_sample_constrained"] is True
    assert f"SMALL_SAMPLE:{n}" in r.report.warnings


async def test_the_orientation_groups_are_declared_provisional(edited: Callable[..., McpPort]) -> None:
    port = edited(min_peers(5))
    r = await run_step_v1(peers_step(), port)
    assert "PROVISIONAL_DEFINITION:orientation_group" in r.report.warnings


@pytest.mark.parametrize("statements", [[], ["PENDING"]])
async def test_without_an_approved_minimum_the_step_stops_with_config_missing(edited: Callable[..., McpPort], statements: list[str]) -> None:
    port = edited(min_peers(5, "PENDING")) if statements else edited()
    r = await run_step_v1(peers_step(), port)
    assert r.report.state == "failed" and r.report.error and r.report.error.code == "CONFIG_MISSING"
    assert "min_peer_count" in r.report.error.message and await listed(port) == []


async def test_a_target_that_is_not_a_unit_is_refused(edited: Callable[..., McpPort]) -> None:
    port = edited(min_peers(5))
    r = await run_step_v1(v1("fetch_peer_candidates", {"entities": [ent("Tòa Aqua 1", "ZONE")]}, question="phân khu Tòa Aqua 1"), port)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "INVALID_SPEC"


@pytest.mark.parametrize("spec", [{}, {"scope_all": True}, {"entities": [ent("A12-08"), ent("A12-11")]}])
async def test_the_target_is_exactly_one_unit_named_directly(alice: McpPort, spec: dict[str, Any]) -> None:
    r = await run_step_v1(v1("fetch_peer_candidates", spec), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "INVALID_SPEC"


async def test_a_target_without_a_usable_area_is_data_unavailable_and_area_m2_is_never_used(edited: Callable[..., McpPort]) -> None:
    port = edited(min_peers(5), "UPDATE dim_unit_master SET net_area_m2 = 'n/a' WHERE unit_code = 'A12-08'")
    r = await run_step_v1(peers_step(), port)
    assert r.report.state == "failed" and r.report.error and r.report.error.code == "SUBJECT_AREA_UNAVAILABLE" and await listed(port) == []


async def test_a_candidate_without_a_usable_area_is_left_out_and_said(edited: Callable[..., McpPort], re_db: str) -> None:
    gone = sorted(expected_peers(re_db, TARGET, ["MID"]))[0]
    port = edited(min_peers(1), f"UPDATE dim_unit_master SET net_area_m2 = '' WHERE unit_code = '{gone}'")
    r = await run_step_v1(peers_step(), port)
    candidates = {c["unit_code"] for c in (await peer_set(port, r))["peer_set"]["candidates"]}
    assert gone not in candidates and "PEER_AREA_UNAVAILABLE:1" in r.report.warnings


async def test_a_peer_search_never_reaches_another_users_project(edited: Callable[..., McpPort]) -> None:
    port = edited(min_peers(5))
    payload = await peer_set(port, await run_step_v1(peers_step(), port))
    assert {u["project_key"] for u in payload["tables"]["dim_unit_master"]} == {"PRJ-X"}


# ---- fetch_unit_context -----------------------------------------------------------------------------------------------------


def ctx_step(entities: list[dict[str, str]], groups: list[str] | None = None, **over: Any) -> Any:
    spec: dict[str, Any] = {"entities": entities}
    if groups is not None:
        spec["context_groups"] = groups
    return v1("fetch_unit_context", spec, question="Vì sao bán chậm?", **over)


async def test_every_group_is_read_for_the_units_of_a_zone(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(ctx_step([ent("Tòa Landmark 1", "ZONE")]), alice)
    assert r.report.state == "completed", r.report.error
    tables = (await artifacts_of(alice, r))["dataset"]["payload"]["tables"]
    units = {e[0] for e in truth(re_db, "SELECT unit_key FROM dim_unit_master WHERE zone_key = 'ZN-A'")}
    assert {u["unit_key"] for u in tables["dim_unit_master"]} == units
    price = truth(re_db, "SELECT p.unit_key, p.effective_date FROM fact_unit_price_history p JOIN dim_unit_master u ON u.unit_key = p.unit_key"
                         " WHERE u.zone_key = 'ZN-A' AND p.effective_date <= '2026-09-28'")
    assert sorted((p["unit_key"], p["effective_date"]) for p in tables["fact_unit_price_history"]) == sorted(price)
    funnel = truth(re_db, "SELECT f.unit_key, f.date_key FROM fact_sales_funnel_daily f JOIN dim_unit_master u ON u.unit_key = f.unit_key"
                          " WHERE u.zone_key = 'ZN-A' AND f.date_key BETWEEN 20260830 AND 20260928")
    assert sorted((f["unit_key"], f["date_key"]) for f in tables["fact_sales_funnel_daily"]) == sorted(funnel) and funnel
    comps = truth(re_db, "SELECT comp_key FROM dim_secondary_market_comps WHERE project_key = 'PRJ-X' AND transaction_date <= '2026-09-28'"
                         " AND unit_type IN (SELECT DISTINCT unit_type FROM dim_unit_master WHERE zone_key = 'ZN-A')")
    assert sorted(c["comp_key"] for c in tables["dim_secondary_market_comps"]) == sorted(c[0] for c in comps) and comps
    assert {m["month_key"] for m in tables["fact_market_macro_monthly"]} <= {202509, 202609} | {202510, 202511, 202512} | set(range(202601, 202610))
    assert all(m["market_id"] == "MKT-HCM-E" and m["segment"] == "HIGH_END" and m["month_key"] <= 202609 for m in tables["fact_market_macro_monthly"])
    assert len(tables["dim_infrastructure_assets"]) == 3 and {a["project_key"] for a in tables["dim_infrastructure_assets"]} == {"PRJ-X"}


async def test_only_the_groups_asked_for_are_read(alice: McpPort) -> None:
    r = await run_step_v1(ctx_step([ent("A12-08", "UNIT")], ["price"]), alice)
    tables = (await artifacts_of(alice, r))["dataset"]["payload"]["tables"]
    assert "fact_unit_price_history" in tables
    assert not {"fact_sales_funnel_daily", "dim_secondary_market_comps", "fact_market_macro_monthly", "dim_infrastructure_assets"} & set(tables)


async def test_a_group_name_outside_the_vocabulary_is_refused(alice: McpPort) -> None:
    r = await run_step_v1(ctx_step([ent("A12-08", "UNIT")], ["weather"]), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "INVALID_SPEC"


async def test_a_missing_macro_month_or_infrastructure_is_a_limitation_not_an_omission(edited: Callable[..., McpPort]) -> None:
    port = edited("DELETE FROM fact_market_macro_monthly WHERE month_key = 202609", "DELETE FROM dim_infrastructure_assets WHERE project_key = 'PRJ-X'")
    r = await run_step_v1(ctx_step([ent("A12-08", "UNIT")], ["macro", "infra"]), port)
    assert r.report.state == "completed", r.report.error
    assert "MACRO_MONTH_MISSING:202609" in r.report.warnings and "INFRA_MISSING:PRJ-X" in r.report.warnings


async def test_no_limitation_when_the_macro_month_and_the_infrastructure_are_there(alice: McpPort) -> None:
    r = await run_step_v1(ctx_step([ent("A12-08", "UNIT")], ["macro", "infra"]), alice)
    assert not any(w.startswith(("MACRO_MONTH_MISSING", "INFRA_MISSING")) for w in r.report.warnings)


async def test_the_context_bundle_keeps_the_three_artifacts_and_its_population(alice: McpPort) -> None:
    r = await run_step_v1(ctx_step([ent("A12-08", "UNIT")], ["price", "funnel"]), alice)
    arts = await artifacts_of(alice, r)
    assert set(arts) == {"dataset", "metric", "dq"}
    population = arts["dataset"]["payload"]["population"]
    assert population["context_groups"] == ["price", "funnel"] and population["funnel_window_days"] == 30
