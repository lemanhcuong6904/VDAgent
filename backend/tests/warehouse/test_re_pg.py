"""The Postgres read path of the real-estate DW (`re_*` tools over the DATA team's real warehouse).

Pure checks run everywhere. The rest needs the warehouse restored and `docker/warehouse/apply-views.sh` applied, and
skips without `VDAGENT_TEST_PG_DSN`, e.g. postgresql://vdagent_reader:<password>@localhost:5433/cdw.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from vdagent_backend.warehouse import RealEstateWarehouse, SqlError
from vdagent_backend.warehouse import re_pg
from vdagent_contracts.scope import AuthorizedScope

DSN = os.environ.get("VDAGENT_TEST_PG_DSN", "")
needs_pg = pytest.mark.skipif(not DSN, reason="VDAGENT_TEST_PG_DSN not set (real warehouse in Postgres)")
ALL = AuthorizedScope(project_ids=["100", "200", "300", "400", "500"])
P100, P200 = AuthorizedScope(project_ids=["100"]), AuthorizedScope(project_ids=["200"])
NOBODY = AuthorizedScope()


def q(sql: str, scope: AuthorizedScope = ALL, timeout_s: float = 20.0):  # noqa: ANN201
    return re_pg.scoped_query(DSN, sql, scope, timeout_s=timeout_s)


def scalar(sql: str, scope: AuthorizedScope = ALL) -> object:
    return q(sql, scope).rows[0][0]


# ---- pure: what a query may look like -------------------------------------------------------------------------------


def test_check_query_accepts_one_select_and_strips_the_semicolon() -> None:
    assert re_pg.check_query("SELECT 1 FROM dim_unit_master;") == "SELECT 1 FROM dim_unit_master"
    assert re_pg.check_query("WITH x AS (SELECT unit_key FROM dim_unit_master) SELECT * FROM x")


@pytest.mark.parametrize("sql", [
    "SELECT 1; SELECT 2",
    "DELETE FROM dim_unit_master",
    "UPDATE dim_unit_master SET unit_type = 'x'",
    "DROP TABLE dim_unit_master",
    "SELECT * INTO leak FROM dim_unit_master",
    "WITH d AS (DELETE FROM dim_unit_master RETURNING *) SELECT * FROM d",
    "",
    "SELEC oops",
])
def test_check_query_rejects_anything_but_a_single_read(sql: str) -> None:
    with pytest.raises(SqlError):
        re_pg.check_query(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM re.dim_unit_master",
    "SELECT * FROM gold.dim_unit_master",
    "SELECT * FROM public.dim_unit_master",
    "SELECT * FROM unit_scope",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM generate_series(1, 3)",
])
def test_check_query_rejects_other_schemas_internal_views_and_table_functions(sql: str) -> None:
    with pytest.raises(SqlError):
        re_pg.check_query(sql)


@pytest.mark.parametrize("sql", [
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_sleep(60)",
    "SELECT set_config('search_path', 'gold', false)",
    "SELECT lo_import('/etc/passwd')",
])
def test_check_query_rejects_dangerous_functions(sql: str) -> None:
    with pytest.raises(SqlError):
        re_pg.check_query(sql)


def test_the_canonical_tables_are_the_ones_the_agents_read() -> None:
    assert "dim_unit_master" in re_pg.TABLES and "snapshot_manifest" in re_pg.TABLES
    assert "unit_scope" not in re_pg.TABLES and "users" not in re_pg.TABLES


def test_a_postgres_dsn_selects_the_postgres_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake(dsn: str, sql: str, scope: AuthorizedScope, *, timeout_s: float):  # noqa: ANN202
        seen.append(dsn)
        raise SqlError("stop")

    monkeypatch.setattr(re_pg, "scoped_query", fake)
    import asyncio

    with pytest.raises(SqlError):
        asyncio.run(RealEstateWarehouse("postgresql://u:p@h/db").query("SELECT 1 FROM dim_unit_master", P100))
    assert seen == ["postgresql://u:p@h/db"]


def test_a_file_path_still_selects_the_sqlite_mock(tmp_path) -> None:  # noqa: ANN001
    import asyncio

    from vdagent_backend.re_warehouse import build

    path = str(tmp_path / "re.db")
    build(path)
    result = asyncio.run(RealEstateWarehouse(path).query("SELECT COUNT(*) FROM dim_unit_master", AuthorizedScope(project_ids=["PRJ-X"])))
    assert result.rows[0][0] > 0


# ---- pure: connecting over a flaky network (a remote warehouse, e.g. AWS RDS) ---------------------------------------


class _FakeConn:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: object) -> None:
        self.statements.append(statement if isinstance(statement, str) else repr(statement))

    def close(self) -> None:
        self.closed = True


def _flaky_connect(monkeypatch: pytest.MonkeyPatch, failures: int) -> list[_FakeConn]:
    """`psycopg.connect` fails `failures` times with a connection timeout, then succeeds."""
    made: list[_FakeConn] = []
    calls = {"n": 0}

    def fake(dsn: str, **kwargs: object) -> _FakeConn:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise psycopg.errors.ConnectionTimeout("connection timeout expired")
        made.append(_FakeConn())
        return made[-1]

    monkeypatch.setattr(re_pg.psycopg, "connect", fake)
    monkeypatch.setattr(re_pg, "_RETRY_DELAY_S", 0.0)
    return made


def test_a_dropped_connection_attempt_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _flaky_connect(monkeypatch, failures=re_pg.CONNECT_ATTEMPTS - 1)
    assert re_pg._connect("postgresql://u:p@h/db", P100, 10.0) is made[0]  # pyright: ignore[reportPrivateUsage]


def test_the_warehouse_is_unavailable_after_every_attempt_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _flaky_connect(monkeypatch, failures=re_pg.CONNECT_ATTEMPTS)
    with pytest.raises(SqlError, match="warehouse unavailable: ConnectionTimeout"):
        re_pg._connect("postgresql://u:p@h/db", P100, 10.0)  # pyright: ignore[reportPrivateUsage]
    assert made == []


def test_the_scope_is_set_up_in_one_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _flaky_connect(monkeypatch, failures=0)
    re_pg._connect("postgresql://u:p@h/db", P100, 10.0)  # pyright: ignore[reportPrivateUsage]
    (sent,) = made[0].statements
    for table in ("dim_unit_master", "fact_unit_price_history"):
        assert f"CREATE TEMP VIEW {table}" in sent or f'CREATE TEMP VIEW "{table}"' in sent
    assert sent.index("SET TRANSACTION READ WRITE") < sent.index("CREATE TEMP VIEW") < sent.rindex(
        "default_transaction_read_only = on")
    assert "statement_timeout" in sent


# ---- live: the scope barrier and the canonical shape ----------------------------------------------------------------


@needs_pg
def test_the_snapshot_manifest_has_the_canonical_shape() -> None:
    result = q("SELECT snapshot_id, snapshot_date_key, status, semantic_config_version, loaded_at FROM snapshot_manifest")
    assert [c["name"] for c in result.columns] == ["snapshot_id", "snapshot_date_key", "status", "semantic_config_version", "loaded_at"]
    assert result.rows == [["SNAP-20260630-01", 20260630, "APPROVED", "3.1.0", "2026-06-30T00:00:00Z"]]


@needs_pg
def test_semantic_config_gives_the_area_tolerance_as_a_ratio() -> None:
    result = q("SELECT config_key, config_value, status FROM semantic_config WHERE config_version = '3.1.0'"
               " AND config_key IN ('peer_area_tolerance_pct', 'overdue_threshold_days')")
    assert {r[0]: (r[1], r[2]) for r in result.rows} == {"peer_area_tolerance_pct": ('"0.10"', "APPROVED"),
                                                          "overdue_threshold_days": ("90", "APPROVED")}


@needs_pg
def test_keys_are_text_and_decimals_travel_as_strings() -> None:
    result = q("SELECT unit_key, project_key, net_area_m2 FROM dim_unit_master WHERE unit_code = 'OCP-U00001'", P100)
    [[unit_key, project_key, net_area]] = result.rows
    assert (unit_key, project_key) == ("100001", "100") and isinstance(net_area, str)


@needs_pg
def test_a_scope_only_sees_its_own_projects() -> None:
    assert scalar("SELECT COUNT(DISTINCT project_key) FROM dim_unit_master", P100) == 1
    assert scalar("SELECT COUNT(*) FROM dim_unit_master WHERE project_key = '200'", P100) == 0
    assert scalar("SELECT COUNT(DISTINCT project_key) FROM dim_unit_master", ALL) == 5


@needs_pg
def test_an_empty_scope_sees_nothing_not_even_a_count() -> None:
    assert scalar("SELECT COUNT(*) FROM dim_unit_master", NOBODY) == 0
    assert scalar("SELECT COUNT(*) FROM fact_unit_inventory_snapshot", NOBODY) == 0


@needs_pg
def test_unit_keyed_tables_are_scoped_through_the_unit() -> None:
    p100 = scalar("SELECT COUNT(*) FROM dm_unit_friction_diagnostics", P100)
    p200 = scalar("SELECT COUNT(*) FROM dm_unit_friction_diagnostics", P200)
    total = scalar("SELECT COUNT(*) FROM dm_unit_friction_diagnostics", ALL)
    assert 0 < p100 < total and 0 < p200 < total and p100 + p200 < total
    assert scalar("SELECT COUNT(*) FROM fact_sales_funnel_daily f JOIN dim_unit_master u ON u.unit_key = f.unit_key"
                  " WHERE u.project_key <> '100'", P100) == 0


@needs_pg
def test_a_zone_grant_shows_only_that_zone() -> None:
    zone = AuthorizedScope(zone_ids=["101"])
    assert scalar("SELECT COUNT(DISTINCT zone_key) FROM dim_unit_master", zone) == 1
    assert scalar("SELECT COUNT(DISTINCT project_key) FROM dim_unit_master", zone) == 1


@needs_pg
def test_a_query_that_forgets_its_own_filter_cannot_leak() -> None:
    result = q("SELECT DISTINCT u.project_key FROM dim_unit_master u JOIN fact_unit_inventory_snapshot i USING (unit_key)", P100)
    assert result.rows == [["100"]]


@needs_pg
def test_the_reader_is_read_only_and_cannot_reach_gold() -> None:
    conn = psycopg.connect(DSN, autocommit=True)
    try:
        with pytest.raises(psycopg.Error):
            conn.execute("DELETE FROM re.dim_unit_master")
        with pytest.raises(psycopg.Error):
            conn.execute("SELECT count(*) FROM gold.dim_unit_master")
    finally:
        conn.close()


@needs_pg
def test_a_qualified_name_is_refused_before_it_reaches_the_database() -> None:
    with pytest.raises(SqlError):
        q("SELECT COUNT(*) FROM gold.dim_unit_master")


@needs_pg
def test_a_runaway_query_is_cancelled() -> None:
    with pytest.raises(SqlError, match="time limit"):
        q("SELECT COUNT(*) FROM fact_sales_funnel_daily a CROSS JOIN fact_sales_funnel_daily b", ALL, timeout_s=0.5)


@needs_pg
def test_the_result_is_capped_and_flagged_truncated() -> None:
    result = q("SELECT unit_key FROM dim_unit_master ORDER BY unit_key")
    assert result.truncated and len(result.rows) == 10_000


@needs_pg
def test_duplicate_column_names_are_made_unique() -> None:
    result = q("SELECT project_key, project_key FROM dim_project_profile ORDER BY project_key", ALL)
    assert [c["name"] for c in result.columns] == ["project_key", "project_key_2"]


@needs_pg
def test_tables_and_describe_count_only_the_scope() -> None:
    tables = {t["name"]: t["row_count"] for t in re_pg.scoped_tables(DSN, P100, timeout_s=20)}
    assert tables["dim_unit_master"] == 3000 and tables["snapshot_manifest"] == 1
    described = re_pg.scoped_describe(DSN, "dim_unit_master", P100, timeout_s=20)
    assert {"unit_key", "unit_code", "net_area_m2"} <= {c["name"] for c in described["columns"]}
    assert all(row[described["columns"].index(next(c for c in described["columns"] if c["name"] == "project_key"))] == "100"
               for row in described["sample_rows"])
    with pytest.raises(SqlError):
        re_pg.scoped_describe(DSN, "unit_scope", P100, timeout_s=20)
