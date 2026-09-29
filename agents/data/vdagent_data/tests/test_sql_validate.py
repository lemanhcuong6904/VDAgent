"""S4 SQL linter (build spec 02 §7): one passing and one violating case per code, plus filter injection."""

from __future__ import annotations

import pytest

from vdagent_contracts.scope import AuthorizedScope
from vdagent_data.sql.validate import validate

SNAP = 20260928
ALICE = AuthorizedScope(project_ids=["PRJ-X"])
OK_SQL = (
    "SELECT m.floor_band, COUNT(*) AS n FROM fact_unit_inventory_snapshot f"
    " JOIN dim_unit_master m ON m.unit_key = f.unit_key WHERE f.inventory_status = 'AVAILABLE' GROUP BY m.floor_band"
)


def codes(sql: str) -> list[str]:
    return [v.code for v in validate(sql, snapshot_key=SNAP, scope=ALICE).violations]


def test_ok_query_passes() -> None:
    result = validate(OK_SQL, snapshot_key=SNAP, scope=ALICE)
    assert result.ok and result.violations == ()


def test_parse_error() -> None:
    assert codes("SELEC floor_band FROM") == ["PARSE_ERROR"]


def test_multi_statement() -> None:
    assert codes(OK_SQL + "; SELECT 1") == ["MULTI_STATEMENT"]
    assert codes(OK_SQL + ";") == []


def test_not_select() -> None:
    assert codes("DELETE FROM dim_unit_master") == ["NOT_SELECT"]
    assert codes("UPDATE dim_unit_master SET unit_type = '1PN'") == ["NOT_SELECT"]
    assert codes("WITH x AS (SELECT unit_key FROM dim_unit_master) SELECT unit_key FROM x") == []


def test_table_not_allowed() -> None:
    assert codes("SELECT * FROM users") == ["TABLE_NOT_ALLOWED"]
    assert codes("SELECT name FROM sqlite_master") == ["TABLE_NOT_ALLOWED"]


def test_column_not_allowed() -> None:
    assert codes("SELECT m.salary FROM dim_unit_master m") == ["COLUMN_NOT_ALLOWED"]
    assert codes("SELECT owner_phone FROM dim_unit_master") == ["COLUMN_NOT_ALLOWED"]
    assert codes("SELECT unit_code AS code FROM dim_unit_master ORDER BY code") == []


def test_join_not_allowed_returns_fix() -> None:
    result = validate(
        "SELECT p.project_name, SUM(s.leads) FROM fact_sales_funnel_daily s"
        " JOIN dim_project_profile p ON p.project_key = s.unit_key GROUP BY p.project_name",
        snapshot_key=SNAP, scope=ALICE,
    )
    assert [v.code for v in result.violations] == ["JOIN_NOT_ALLOWED"]
    assert "dim_unit_master.project_key" in result.violations[0].fix
    other = validate(
        "SELECT 1 FROM fact_sales_funnel_daily s JOIN fact_market_macro_monthly k ON k.month_key = s.date_key",
        snapshot_key=SNAP, scope=ALICE,
    )
    assert [v.code for v in other.violations] == ["JOIN_NOT_ALLOWED"] and other.violations[0].fix


def test_hardcoded_threshold() -> None:
    result = validate(
        "SELECT COUNT(*) FROM fact_unit_inventory_snapshot f WHERE f.unsold_days_dom > 90", snapshot_key=SNAP, scope=ALICE
    )
    assert [v.code for v in result.violations] == ["HARDCODED_THRESHOLD"]
    assert "overdue_threshold_days" in result.violations[0].fix
    assert codes("SELECT COUNT(*) FROM fact_unit_inventory_snapshot f WHERE f.unsold_days_dom > :overdue_threshold_days") == []


def test_inject_snapshot_filter_every_fact() -> None:
    result = validate(
        "SELECT c.cause_code, COUNT(*) FROM unit_diagnostic_causes c"
        " JOIN fact_unit_inventory_snapshot f ON f.unit_key = c.unit_key GROUP BY c.cause_code",
        snapshot_key=SNAP, scope=ALICE,
    )
    assert result.ok and result.sql is not None
    assert "f.snapshot_date_key = 20260928" in result.sql
    assert "c.snapshot_date_key = 20260928" in result.sql


def test_inject_rbac_every_project_keyed_table() -> None:
    result = validate(OK_SQL, snapshot_key=SNAP, scope=AuthorizedScope(project_ids=["PRJ-X"], zone_ids=["ZN-D"]))
    assert result.sql is not None
    assert "f.project_key IN ('PRJ-X')" in result.sql and "f.zone_key IN ('ZN-D')" in result.sql
    assert "m.project_key IN ('PRJ-X')" in result.sql
    unit_only = validate("SELECT unit_key FROM fact_unit_price_history", snapshot_key=SNAP, scope=ALICE)
    assert unit_only.sql is not None and "unit_key IN (SELECT" in unit_only.sql and "dim_unit_master" in unit_only.sql
    left = validate(
        "SELECT f.unit_key, c.channel_name FROM fact_unit_inventory_snapshot f"
        " LEFT JOIN dm_unit_friction_diagnostics d ON d.unit_key = f.unit_key"
        " LEFT JOIN dim_sales_channel c ON c.channel_key = f.channel_key",
        snapshot_key=SNAP, scope=ALICE,
    )
    assert left.sql is not None
    on_clause = left.sql.split(" WHERE ")[0]
    assert "d.snapshot_date_key = 20260928" in on_clause  # LEFT JOIN filters go in ON, keeping the outer join


@pytest.mark.parametrize("scope", [AuthorizedScope(), AuthorizedScope(project_ids=[])])
def test_empty_scope_sees_nothing(scope: AuthorizedScope) -> None:
    result = validate(OK_SQL, snapshot_key=SNAP, scope=scope)
    assert result.sql is not None and "IN (NULL)" in result.sql
