"""Data quality sensors (SPEC §3.5: the schema does not catch everything) and the metric columns the warehouse really holds.

Each sensor is proven twice: clean data reports no violation, and a tampered copy of the DW reports exactly what was broken.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.core import McpIdentity
from vdagent_data.steps import run_step
from vdagent_data.tests.conftest import ALICE, McpPort
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_data.tests.test_steps import artifacts_of, metric, step

PEERS = {"subject_unit_code": "A12-08", "population": "peer_candidates"}


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


def sensors(dq: dict[str, Any]) -> dict[str, int]:
    return {s["name"]: s["violations"] for s in dq["payload"]["sensors"]}


async def test_clean_data_reports_no_violation(alice: McpPort) -> None:
    report = await run_step(step(spec=PEERS), alice)
    dq = (await artifacts_of(alice, report))["dq"]
    assert set(sensors(dq)) == {"sold_without_sold_date", "sold_date_on_available_unit", "negative_dom", "inventory_project_mismatch"}
    assert set(sensors(dq).values()) == {0}
    assert not any(w.startswith("DQ_VIOLATION") for w in report.warnings)


@pytest.mark.parametrize("sql,name", [
    ("UPDATE fact_unit_inventory_snapshot SET sold_date = NULL WHERE snapshot_date_key = 20260928 AND unit_key IN (SELECT unit_key FROM"
     " fact_unit_inventory_snapshot WHERE snapshot_date_key = 20260928 AND inventory_status = 'SOLD' AND unit_key IN (SELECT unit_key FROM"
     " dim_unit_master WHERE project_key = 'PRJ-X' AND unit_type = (SELECT unit_type FROM dim_unit_master WHERE unit_code = 'A12-08')) LIMIT 1)",
     "sold_without_sold_date"),
    ("UPDATE fact_unit_inventory_snapshot SET sold_date = '2026-09-01' WHERE snapshot_date_key = 20260928 AND inventory_status = 'AVAILABLE'"
     " AND unit_key = 'U-PRJ-X-A12-11'", "sold_date_on_available_unit"),
    ("UPDATE fact_unit_inventory_snapshot SET unsold_days_dom = -3 WHERE snapshot_date_key = 20260928 AND unit_key = 'U-PRJ-X-A12-11'", "negative_dom"),
])
async def test_a_broken_row_is_reported_by_its_sensor(edited: Callable[..., McpPort], sql: str, name: str) -> None:
    port = edited(sql)
    report = await run_step(step(spec=PEERS), port)
    assert report.state == "completed", report.error
    dq = (await artifacts_of(port, report))["dq"]
    assert sensors(dq)[name] >= 1 and {n for n, v in sensors(dq).items() if v} == {name}
    assert any(w.startswith(f"DQ_VIOLATION:{name}:") for w in report.warnings) and dq["payload"]["overall_status"] == "PARTIAL"


# the scoped views hide a row whose project is outside the scope, so this sensor is proven on the function itself
def test_the_project_mismatch_sensor_compares_the_row_with_its_unit() -> None:
    from vdagent_data.steps import _sensors  # noqa: PLC0415

    units = [{"unit_key": "U1", "project_key": "P1"}, {"unit_key": "U2", "project_key": "P1"}]
    rows = [{"unit_key": "U1", "project_key": "P1", "inventory_status": "AVAILABLE", "unsold_days_dom": 5},
            {"unit_key": "U2", "project_key": "P2", "inventory_status": "AVAILABLE", "unsold_days_dom": 5}]
    found, limits = _sensors(units, rows)
    assert {s["name"]: s["violations"] for s in found}["inventory_project_mismatch"] == 1
    assert limits == ["DQ_VIOLATION:inventory_project_mismatch:1"]


def test_a_sensor_skips_a_column_the_warehouse_does_not_have() -> None:
    from vdagent_data.steps import _sensors  # noqa: PLC0415

    found, limits = _sensors([{"unit_key": "U1", "project_key": "P1"}], [{"unit_key": "U1", "inventory_status": "SOLD", "unsold_days_dom": 1}])
    assert {s["name"]: s["violations"] for s in found}["sold_without_sold_date"] == 0 and limits == []


# ---- the metric columns of the real warehouse ---------------------------------------------------------------------------------


async def test_discount_and_subsidy_are_read_from_the_inventory_row_when_the_warehouse_carries_them(edited: Callable[..., McpPort]) -> None:
    port = edited("ALTER TABLE fact_unit_inventory_snapshot ADD COLUMN discount_pct REAL",
                  "ALTER TABLE fact_unit_inventory_snapshot ADD COLUMN subsidy_duration_mo INTEGER",
                  "UPDATE fact_unit_inventory_snapshot SET discount_pct = 4.3, subsidy_duration_mo = 12"
                  " WHERE snapshot_date_key = 20260928 AND unit_key = 'U-PRJ-X-A12-08'")
    report = await run_step(step(), port)
    arts = await artifacts_of(port, report)
    assert metric(arts["metric"], "discount_pct")["value"] == "4.3"
    assert metric(arts["metric"], "discount_pct")["source_ref"] == "re:fact_unit_inventory_snapshot.discount_pct"
    assert metric(arts["metric"], "subsidy_duration_mo")["value"] == 12
    assert metric(arts["metric"], "subsidy_duration_mo")["source_ref"] == "re:fact_unit_inventory_snapshot.subsidy_duration_mo"
    assert "METRIC_UNAVAILABLE:discount_pct" not in arts["metric"]["limitations"]


async def test_without_those_columns_the_old_sources_and_the_null_rule_hold(alice: McpPort) -> None:
    report = await run_step(step(), alice)
    arts = await artifacts_of(alice, report)
    assert metric(arts["metric"], "discount_pct")["value"] is None and "METRIC_UNAVAILABLE:discount_pct" in arts["metric"]["limitations"]
    assert metric(arts["metric"], "subsidy_duration_mo")["source_ref"] == "re:dm_unit_friction_diagnostics.subsidy_duration_mo"
