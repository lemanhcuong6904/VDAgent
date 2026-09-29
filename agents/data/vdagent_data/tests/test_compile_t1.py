"""T1 semantic compiler (build spec 02 §6): names in, SQL + lineage out; numbers checked on the DW mock."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from vdagent_backend.re_warehouse import build  # test-only (DEC-032)
from vdagent_contracts.scope import AuthorizedScope
from vdagent_data.sql.compile_t1 import compile_t1, render
from vdagent_data.sql.validate import validate

SNAP = 20260928
ALICE = AuthorizedScope(project_ids=["PRJ-X"])
CONFIG = {"overdue_threshold_days": 90}


@pytest.fixture(scope="module")
def dw(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    path = Path(tmp_path_factory.mktemp("dw")) / "re.db"
    build(str(path))
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


def run(dw: sqlite3.Connection, metrics: list[str], group_by: list[str] = [], filters: list[str] = [],
        scope_filters: dict[str, list[str]] | None = None, config: dict[str, int] = CONFIG) -> list[dict[str, object]]:
    compiled = compile_t1(metrics, group_by, filters, scope_filters=scope_filters or {})
    checked = validate(compiled.sql, snapshot_key=SNAP, scope=ALICE)
    assert checked.ok, checked.violations
    assert checked.sql is not None
    cur = dw.execute(render(checked.sql, config))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def test_t1_absorption_rate(dw: sqlite3.Connection) -> None:
    [row] = run(dw, ["absorption_rate"])
    sold, released = dw.execute(
        "SELECT SUM(inventory_status = 'SOLD'), SUM(release_date <= snapshot_date) FROM fact_unit_inventory_snapshot"
        " WHERE snapshot_date_key = ? AND project_key = 'PRJ-X'",
        (SNAP,),
    ).fetchone()
    assert (row["absorption_rate__num"], row["absorption_rate__den"]) == (sold, released)
    assert isinstance(row["absorption_rate__num"], int)


def test_t1_avg_dom_unsold(dw: sqlite3.Connection) -> None:
    [row] = run(dw, ["avg_dom_unsold"], scope_filters={"zone_key": ["ZN-C"]})
    total, n = dw.execute(
        "SELECT SUM(unsold_days_dom), COUNT(*) FROM fact_unit_inventory_snapshot"
        " WHERE snapshot_date_key = ? AND zone_key = 'ZN-C' AND inventory_status = 'AVAILABLE'",
        (SNAP,),
    ).fetchone()
    assert (row["avg_dom_unsold__num"], row["avg_dom_unsold__den"]) == (total, n) and n == 41  # 40 overdue + C05-02


def test_t1_slow_moving_threshold_from_config(dw: sqlite3.Connection) -> None:
    compiled = compile_t1(["slow_moving_count"], [], ["slow_moving"])
    assert "90" not in compiled.sql and ":overdue_threshold_days" in compiled.sql
    assert compiled.config_keys == ("overdue_threshold_days",)
    [at_90] = run(dw, ["slow_moving_count"], scope_filters={"zone_key": ["ZN-C"]})
    [at_60] = run(dw, ["slow_moving_count"], scope_filters={"zone_key": ["ZN-C"]}, config={"overdue_threshold_days": 60})
    assert at_90["slow_moving_count__num"] == 40 and at_60["slow_moving_count__num"] == 40
    [strict] = run(dw, ["slow_moving_count"], scope_filters={"zone_key": ["ZN-C"]}, config={"overdue_threshold_days": 150})
    assert strict["slow_moving_count__num"] < 40
    with pytest.raises(KeyError):
        render(compiled.sql, {})


def test_t1_group_by_floor_band(dw: sqlite3.Connection) -> None:
    rows = run(dw, ["avg_dom_unsold", "unit_count"], ["floor_band"], ["released"], scope_filters={"zone_key": ["ZN-A", "ZN-B"]})
    assert [r["floor_band"] for r in rows] == sorted(r["floor_band"] for r in rows)
    assert sum(int(r["unit_count__num"]) for r in rows) == dw.execute(  # type: ignore[call-overload]
        "SELECT COUNT(*) FROM fact_unit_inventory_snapshot WHERE snapshot_date_key = ? AND zone_key IN ('ZN-A','ZN-B')"
        " AND release_date <= snapshot_date",
        (SNAP,),
    ).fetchone()[0]
    assert all("n" in r for r in rows)


def test_t1_lineage_has_formula_id_and_sql_hash() -> None:
    compiled = compile_t1(["absorption_rate", "avg_dom_unsold"], ["zone"], ["released"])
    assert compiled.lineage["formula_ids"] == {"absorption_rate": "F-ABS-01", "avg_dom_unsold": "F-DOM-01"}
    assert compiled.lineage["filters"] == ["released"] and compiled.lineage["group_by"] == ["zone"]
    again = compile_t1(["absorption_rate", "avg_dom_unsold"], ["zone"], ["released"])
    assert compiled.sql_hash == again.sql_hash and len(compiled.sql_hash) == 64
    with pytest.raises(KeyError):
        compile_t1(["profit"], [], [])
