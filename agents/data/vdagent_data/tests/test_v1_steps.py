"""The v1.0 operations of the Data agent (contract_agent.md tab Data, SPEC §2–§3, §6): fetch_units and aggregate_metrics by
entities, scope or filters; the snapshot locked by Data; QUESTIONs from the entity ladder.

Every expected number is computed here with independent SQL on the mock DW, never copied from the agent's output.
Runs on the Backend's real MCP tools over a freshly built `re_warehouse` (see conftest); no LLM.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.core import McpIdentity
from vdagent_contracts.canonical import percentile_inc
from vdagent_contracts.messages import StepSpec
from vdagent_data.steps import ToolFailure  # noqa: F401  (re-exported port error)
from vdagent_data.tests.conftest import ALICE, BOB, McpPort
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_data.v1 import V1Result, run_step_v1

LOCKED = "SNAP-2026-09-28"  # the newest APPROVED snapshot of the mock DW (…-09-29 is a DRAFT)


def v1(operation: str, spec: dict[str, Any], *, question: str = "câu hỏi", user: str = ALICE, **overrides: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": f"t_{user}", "plan_id": "pl_v1", "step_id": "B1", "idempotency_key": "pl_v1:B1", "operation": operation, "spec": spec,
        "user_context": {"user_id": user, "authorized_scope": {"project_ids": [], "zone_ids": []}},
        "snapshot_id": None, "semantic_config_version": None, "original_question": question,
    }
    fields.update(overrides)
    return StepSpec.model_validate(fields)


def ent(mention: str, hint: str = "UNKNOWN") -> dict[str, str]:
    return {"mention": mention, "kind_hint": hint}


async def artifacts_of(port: McpPort, result: V1Result) -> dict[str, dict[str, Any]]:
    return {r.artifact_type.value: await port.call("artifact_get", {"artifact_id": r.artifact_id, "version": r.version})
            for r in result.report.artifact_refs}


async def listed(port: McpPort) -> list[dict[str, Any]]:
    return (await port.call("artifact_list", {}))["artifacts"]


def truth(re_db: str, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with sqlite3.connect(re_db) as conn:
        return conn.execute(sql, args).fetchall()


UNITS_OF_ZONE = ("SELECT u.unit_key, i.inventory_status, i.unsold_days_dom, i.net_price_per_m2 FROM dim_unit_master u"
                 " JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key AND i.snapshot_date_key = 20260928"
                 " WHERE u.zone_key = ?")


# ---- the snapshot ----------------------------------------------------------------------------------------------------------


async def test_the_agent_locks_the_newest_approved_snapshot_when_the_step_has_none(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-08", "UNIT")]}), alice)
    assert r.report.state == "completed", r.report.error
    assert r.report.snapshot_id == LOCKED and r.report.semantic_config_version == "sc-1"  # read from the manifest, not the message
    arts = await artifacts_of(alice, r)
    assert all(a["snapshot_refs"] == [LOCKED] and a["semantic_config_version"] == "sc-1" for a in arts.values())


async def test_a_given_approved_snapshot_is_used_as_is(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-08", "UNIT")]}, snapshot_id="SNAP-2026-08-31"), alice)
    assert r.report.state == "completed" and r.report.snapshot_id == "SNAP-2026-08-31"


@pytest.mark.parametrize("snapshot,code", [("SNAP-2026-09-29", "SNAPSHOT_NOT_APPROVED"), ("SNAP-NOPE", "SNAPSHOT_UNKNOWN")])
async def test_a_snapshot_that_is_a_draft_or_unknown_is_refused(alice: McpPort, snapshot: str, code: str) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-08", "UNIT")]}, snapshot_id=snapshot), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == code
    assert await listed(alice) == []


async def test_the_step_of_someone_else_is_refused(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"scope_all": True}, user=BOB), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "USER_CONTEXT_MISMATCH"


# ---- what a spec may say -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation,spec", [
    ("fetch_units", {}),                                                            # neither entities nor scope_all
    ("fetch_units", {"scope_all": True, "entities": [ent("A12-08")]}),               # both
    ("fetch_units", {"scope_all": True, "filters": ["cheap"]}),                      # unknown filter
    ("fetch_units", {"scope_all": True, "attributes": ["colour"]}),                  # unknown attribute
    ("fetch_units", {"scope_all": True, "subject_unit_code": "A12-08"}),             # a field of no contract
    ("aggregate_metrics", {"scope_all": True}),                                      # no metric
    ("aggregate_metrics", {"scope_all": True, "metrics": ["profit"]}),               # unknown metric
    ("aggregate_metrics", {"scope_all": True, "metrics": ["unit_count"], "group_by": ["colour"]}),
    ("fetch_units", {"entities": [{"mention": "A12-08", "kind_hint": "HOUSE"}]}),    # unknown kind
])
async def test_a_spec_that_breaks_the_form_or_the_vocabulary_is_rejected_before_any_read(alice: McpPort, operation: str, spec: dict[str, Any]) -> None:
    r = await run_step_v1(v1(operation, spec), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "INVALID_SPEC"
    assert "re_run_query" not in alice.calls  # refused before the warehouse is read
    assert await listed(alice) == []


async def test_an_unknown_operation_is_rejected(alice: McpPort) -> None:
    r = await run_step_v1(v1("delete_units", {"scope_all": True}), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "UNKNOWN_OPERATION"


# ---- fetch_units by entity ---------------------------------------------------------------------------------------------------


async def test_a_unit_is_found_by_its_loosely_typed_code(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("a12 08")]}, question="Vì sao căn a12 08 bán chậm?"), alice)
    assert r.report.state == "completed", r.report.error
    arts = await artifacts_of(alice, r)
    [unit] = arts["dataset"]["payload"]["tables"]["dim_unit_master"]
    assert unit["unit_code"] == "A12-08"
    assert r.resolved == [{"mention": "a12 08", "kind": "UNIT", "id": unit["unit_key"], "name": "A12-08", "method": "normalized"}]


async def test_a_zone_gives_every_unit_of_the_zone_and_nothing_else(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE")]}, question="Tình hình phân khu Tòa Aqua 1?"), alice)
    assert r.report.state == "completed", r.report.error
    expected = truth(re_db, UNITS_OF_ZONE, "ZN-C")
    assert len(expected) > 5
    tables = (await artifacts_of(alice, r))["dataset"]["payload"]["tables"]
    assert sorted(u["unit_key"] for u in tables["dim_unit_master"]) == sorted(e[0] for e in expected)
    assert {u["zone_key"] for u in tables["dim_unit_master"]} == {"ZN-C"}
    assert sorted((i["unit_key"], i["unsold_days_dom"]) for i in tables["fact_unit_inventory_snapshot"]) == sorted((e[0], e[2]) for e in expected)
    assert [z["zone_key"] for z in tables["dim_zone_master"]] == ["ZN-C"] and [p["project_key"] for p in tables["dim_project_profile"]] == ["PRJ-X"]
    assert r.resolved[0]["kind"] == "ZONE" and r.resolved[0]["id"] == "ZN-C" and r.resolved[0]["method"] == "exact"


async def test_a_project_by_name_gives_its_units(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Khu đô thị Sông Xanh", "PROJECT")]}), alice)
    assert r.report.state == "completed", r.report.error
    n = truth(re_db, "SELECT COUNT(*) FROM dim_unit_master WHERE project_key = 'PRJ-X'")[0][0]
    assert (await artifacts_of(alice, r))["dataset"]["payload"]["row_counts"]["dim_unit_master"] == n


async def test_two_entities_give_the_union(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Tòa Aqua 1", "ZONE"), ent("A12-08", "UNIT")]}), alice)
    assert r.report.state == "completed", r.report.error
    zone_units = {e[0] for e in truth(re_db, UNITS_OF_ZONE, "ZN-C")}
    keys = {u["unit_key"] for u in (await artifacts_of(alice, r))["dataset"]["payload"]["tables"]["dim_unit_master"]}
    assert keys == zone_units | {"U-PRJ-X-A12-08"}


async def test_the_answer_of_a_single_unit_keeps_the_shape_the_analysis_agents_read(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-08", "UNIT")]}), alice)
    arts = await artifacts_of(alice, r)
    population = arts["dataset"]["payload"]["population"]
    assert population["subject_unit_key"] == "U-PRJ-X-A12-08" and population["rule"] == "subject"
    rows = {m["metric_id"]: m for m in arts["metric"]["payload"]["metrics"]}
    assert rows["dom_days"]["value"] == 138 and rows["net_price_per_m2_vnd"]["value"] == 72500000


# ---- fetch_units by scope and filter -----------------------------------------------------------------------------------------


async def test_slow_moving_is_available_and_over_the_approved_threshold(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(v1("fetch_units", {"scope_all": True, "filters": ["slow_moving"]}), alice)
    assert r.report.state == "completed", r.report.error
    threshold = int(truth(re_db, "SELECT config_value FROM semantic_config WHERE config_key = 'overdue_threshold_days'")[0][0])
    expected = truth(re_db, "SELECT i.unit_key FROM fact_unit_inventory_snapshot i WHERE i.snapshot_date_key = 20260928"
                            " AND i.project_key = 'PRJ-X' AND i.inventory_status = 'AVAILABLE' AND i.unsold_days_dom > ?", threshold)
    tables = (await artifacts_of(alice, r))["dataset"]["payload"]["tables"]
    assert sorted(i["unit_key"] for i in tables["fact_unit_inventory_snapshot"]) == sorted(e[0] for e in expected)
    assert 0 < len(expected) < 389
    assert {i["inventory_status"] for i in tables["fact_unit_inventory_snapshot"]} == {"AVAILABLE"}


async def test_the_scope_of_the_caller_bounds_scope_all(alice: McpPort, re_db: str) -> None:
    bob = alice.as_user(BOB)
    r = await run_step_v1(v1("fetch_units", {"scope_all": True}, user=BOB), bob)
    assert r.report.state == "completed", r.report.error
    units = (await artifacts_of(bob, r))["dataset"]["payload"]["tables"]["dim_unit_master"]
    assert units and {u["project_key"] for u in units} == {"PRJ-Y"}


async def test_filters_that_leave_nothing_are_an_error_unless_the_step_allows_empty(alice: McpPort) -> None:
    spec = {"scope_all": True, "filters": ["available", "sold"]}
    r = await run_step_v1(v1("fetch_units", spec), alice)
    assert r.report.state == "failed" and r.report.error and r.report.error.code == "EMPTY_POPULATION"
    r = await run_step_v1(v1("fetch_units", {**spec, "success_criteria": {"allow_empty": True}}), alice)
    assert r.report.state == "completed" and "EMPTY_RESULT" in r.report.warnings


async def test_a_need_outside_the_catalog_is_not_served_and_says_so(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-08", "UNIT")], "out_of_catalog_need": "khách hàng nào đã xem căn này"}), alice)
    assert r.report.state == "completed" and any(w.startswith("OUT_OF_CATALOG_NEED_NOT_SERVED") for w in r.report.warnings)


@pytest.fixture
def config_edit(tmp_path: Path, re_db: str, mcp_tools: McpTools) -> Callable[..., McpPort]:
    """A copy of the DW with the given statements applied, served to the agent."""

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


@pytest.mark.parametrize("sql", [
    "DELETE FROM semantic_config WHERE config_key = 'overdue_threshold_days'",
    "UPDATE semantic_config SET status = 'PENDING' WHERE config_key = 'overdue_threshold_days'",
])
async def test_a_rule_that_needs_an_unapproved_threshold_stops_with_config_missing(config_edit: Callable[..., McpPort], sql: str) -> None:
    port = config_edit(sql)
    r = await run_step_v1(v1("fetch_units", {"scope_all": True, "filters": ["slow_moving"]}), port)
    assert r.report.state == "failed" and r.report.error and r.report.error.code == "CONFIG_MISSING"
    assert "overdue_threshold_days" in r.report.error.message and await listed(port) == []


# ---- the ladder asks, never guesses ------------------------------------------------------------------------------------------


async def test_a_name_that_fits_two_zones_asks_with_closed_choices_and_stores_nothing(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Landmark", "ZONE")]}, question="Tại sao phân khu Landmark bán chậm?"), alice)
    assert r.report.state == "input_required" and r.question is not None
    assert r.question.reason_code == "AMBIGUOUS_REQUEST" and r.question.mention == "Landmark"
    assert [(o.kind, o.id, o.name) for o in r.question.options] == [("ZONE", "ZN-B", "Landmark Plaza"), ("ZONE", "ZN-A", "Tòa Landmark 1")]  # by name, so the order never varies
    assert await listed(alice) == []


async def test_the_chosen_option_lets_the_step_run_and_is_reported_as_the_method(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Landmark", "ZONE")]}, question="Tại sao phân khu Landmark bán chậm?"),
                          alice, saved={"landmark": "ZN-B"})
    assert r.report.state == "completed", r.report.error
    assert r.resolved[0]["id"] == "ZN-B" and r.resolved[0]["method"] == "saved_choice"
    assert {u["zone_key"] for u in (await artifacts_of(alice, r))["dataset"]["payload"]["tables"]["dim_unit_master"]} == {"ZN-B"}


async def test_an_unknown_code_asks_with_the_nearest_codes_of_the_callers_scope(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("A12-09", "UNIT")]}, question="Vì sao căn A12-09 bán chậm?"), alice)
    assert r.report.state == "input_required" and r.question is not None and r.question.reason_code == "ENTITY_NOT_FOUND"
    assert "A12-08" in [o.name for o in r.question.options]


async def test_a_name_of_another_users_project_is_not_revealed(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("Tòa Đồi Thông 1", "ZONE")]}, question="phân khu Tòa Đồi Thông 1"), alice)
    assert r.report.state in ("input_required", "rejected") and not r.report.artifact_refs
    names = [o.name for o in (r.question.options if r.question else [])]
    assert set(names) <= {"Tòa Landmark 1", "Landmark Plaza", "Tòa Aqua 1", "Khu đô thị Sông Xanh"}  # Alice's own scope only
    assert "Đồi Thông" not in " ".join(names)


async def test_nothing_that_resembles_the_name_is_out_of_scope(alice: McpPort) -> None:
    r = await run_step_v1(v1("fetch_units", {"entities": [ent("qqqqqq", "ZONE")]}, question="phân khu qqqqqq"), alice)
    assert r.report.state == "rejected" and r.report.error and r.report.error.code == "OUT_OF_SCOPE"


# ---- aggregate_metrics -----------------------------------------------------------------------------------------------------


def quant(value: Decimal, places: str = "0.01") -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


async def test_aggregate_by_zone_matches_independent_sql(alice: McpPort, re_db: str) -> None:
    metrics = ["unit_count", "avg_dom_unsold", "slow_moving_count", "slow_moving_rate", "absorption_rate", "avg_net_price_per_m2", "dom_days"]
    r = await run_step_v1(v1("aggregate_metrics", {"scope_all": True, "metrics": metrics, "group_by": ["zone"]}), alice)
    assert r.report.state == "completed", r.report.error
    rows = {(m["metric_id"], m["subject"]["id"]): m for m in (await artifacts_of(alice, r))["metric"]["payload"]["metrics"]}
    for zone in ("ZN-A", "ZN-B", "ZN-C"):
        units = truth(re_db, UNITS_OF_ZONE, zone)
        available = [u for u in units if u[1] == "AVAILABLE"]
        slow = [u for u in available if u[2] > 90]
        sold = [u for u in units if u[1] == "SOLD"]
        key = lambda m: rows[(m, f"zone_key={zone}")]  # noqa: E731
        assert key("unit_count")["value"] == len(units) and key("unit_count")["n"] == len(units)
        assert key("slow_moving_count")["value"] == len(slow)
        assert key("slow_moving_rate")["value"] == quant(Decimal(100 * len(slow)) / len(available))
        assert (key("slow_moving_rate")["numerator"], key("slow_moving_rate")["denominator"]) == (len(slow), len(available))
        assert key("avg_dom_unsold")["value"] == quant(Decimal(sum(u[2] for u in available)) / len(available))
        assert key("absorption_rate")["value"] == quant(Decimal(100 * len(sold)) / len(units))
        assert key("avg_net_price_per_m2")["value"] == quant(Decimal(sum(u[3] for u in units)) / len(units))
        assert key("dom_days")["value"] == str(percentile_inc([Decimal(u[2]) for u in units], Decimal("0.5")))


async def test_an_unapproved_definition_is_reported_as_provisional(alice: McpPort) -> None:
    r = await run_step_v1(v1("aggregate_metrics", {"scope_all": True, "metrics": ["absorption_rate"]}), alice)
    assert "PROVISIONAL_DEFINITION:absorption_rate" in r.report.warnings
    r = await run_step_v1(v1("aggregate_metrics", {"scope_all": True, "metrics": ["unit_count"]}), alice)
    assert not any(w.startswith("PROVISIONAL_DEFINITION") for w in r.report.warnings)


async def test_aggregate_on_a_named_zone_only_counts_that_zone(alice: McpPort, re_db: str) -> None:
    r = await run_step_v1(v1("aggregate_metrics", {"entities": [ent("Tòa Aqua 1", "ZONE")], "metrics": ["unit_count"]}), alice)
    [row] = (await artifacts_of(alice, r))["metric"]["payload"]["metrics"]
    assert row["value"] == len(truth(re_db, UNITS_OF_ZONE, "ZN-C")) and row["subject"]["type"] == "POPULATION"


async def test_a_metric_the_warehouse_does_not_hold_is_null_with_a_limitation_never_zero(alice: McpPort) -> None:
    r = await run_step_v1(v1("aggregate_metrics", {"scope_all": True, "metrics": ["discount_pct"]}), alice)
    assert r.report.state == "completed" and "METRIC_UNAVAILABLE:discount_pct" in r.report.warnings
    assert all(m["value"] is None for m in (await artifacts_of(alice, r))["metric"]["payload"]["metrics"])


async def test_a_metric_column_the_warehouse_does_hold_is_read(config_edit: Callable[..., McpPort]) -> None:
    port = config_edit("ALTER TABLE fact_unit_inventory_snapshot ADD COLUMN discount_pct REAL",
                       "UPDATE fact_unit_inventory_snapshot SET discount_pct = 2.5 WHERE snapshot_date_key = 20260928 AND unit_key LIKE '%A12-08'")
    r = await run_step_v1(v1("aggregate_metrics", {"entities": [ent("A12-08", "UNIT")], "metrics": ["discount_pct"]}), port)
    [row] = (await artifacts_of(port, r))["metric"]["payload"]["metrics"]
    assert row["value"] == "2.5" and not any(w.startswith("METRIC_UNAVAILABLE") for w in r.report.warnings)


async def test_aggregate_on_a_filter_that_matches_nothing_is_empty_population(alice: McpPort) -> None:
    r = await run_step_v1(v1("aggregate_metrics", {"scope_all": True, "metrics": ["unit_count"], "filters": ["available", "sold"]}), alice)
    assert r.report.state == "failed" and r.report.error and r.report.error.code == "EMPTY_POPULATION"


# ---- what the labels say depends on the warehouse -----------------------------------------------------------------------------


async def test_the_mock_warehouse_is_labelled_synthetic_and_the_real_one_is_not(alice: McpPort) -> None:
    spec = {"entities": [ent("A12-08", "UNIT")]}
    mock = await run_step_v1(v1("fetch_units", spec), alice)
    assert "SYNTHETIC_SOURCE:net_area_m2" in mock.report.warnings and not any(w.startswith("SNAPSHOT_STATUS_ASSUMED") for w in mock.report.warnings)
    real = await run_step_v1(v1("fetch_units", spec), alice, profile="real")
    assert not any(w.startswith(("SYNTHETIC_SOURCE", "BLOCKED:D2b")) for w in real.report.warnings)
    assert "SNAPSHOT_STATUS_ASSUMED" in real.report.warnings
