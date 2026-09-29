"""Read-only, user-scoped SQL over the real-estate DW mock (system prompt §6.3, D8) — the second barrier.

The Data harness injects snapshot and RBAC filters itself; this module makes sure that even a wrong query cannot see
rows outside the caller's `authorized_scope`. Every scoped table is shadowed by a TEMP VIEW of the same name
(SQLite resolves `temp` before `main`), and an authorizer rejects direct reads of `main.<scoped table>`.
Blocking sqlite3 code: callers run it in a worker thread.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from vdagent_backend.mcp.sql import (
    QueryResult,
    SqlError,
    _deadline,  # pyright: ignore[reportPrivateUsage]
    _json_value,  # pyright: ignore[reportPrivateUsage]
    check_select,
    connect_warehouse,
    execute_select,
    quote_ident,
)
from vdagent_contracts.scope import AuthorizedScope

# table → (project column, zone column or None)
_BY_PROJECT: dict[str, tuple[str, str | None]] = {
    "dim_project_profile": ("project_key", None),
    "dim_zone_master": ("project_key", "zone_key"),
    "dim_unit_master": ("project_key", "zone_key"),
    "fact_unit_inventory_snapshot": ("project_key", "zone_key"),
    "fact_sales_channel_performance": ("project_key", None),
    "dim_secondary_market_comps": ("project_key", None),
    "dim_infrastructure_assets": ("project_key", None),
}
# tables keyed by unit only: scoped through dim_unit_master
_BY_UNIT = ("fact_unit_price_history", "fact_sales_funnel_daily", "dm_unit_friction_diagnostics", "unit_diagnostic_causes")
SCOPED_TABLES = frozenset(_BY_PROJECT) | frozenset(_BY_UNIT)


def _literal_list(values: list[str]) -> str:
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")" if values else "(NULL)"


def _unit_predicate(scope: AuthorizedScope) -> str:
    projects, zones = _literal_list(scope.project_ids), _literal_list(scope.zone_ids)
    return (
        "unit_key IN (SELECT unit_key FROM main.dim_unit_master"
        f" WHERE project_key IN {projects} OR zone_key IN {zones})"
    )


def _predicate(table: str, scope: AuthorizedScope) -> str:
    projects, zones = _literal_list(scope.project_ids), _literal_list(scope.zone_ids)
    if table in _BY_UNIT:
        return _unit_predicate(scope)
    project_col, zone_col = _BY_PROJECT[table]
    if zone_col is not None:
        return f"{project_col} IN {projects} OR {zone_col} IN {zones}"
    # project-level tables: projects granted whole, or holding a granted zone
    return (
        f"{project_col} IN {projects} OR {project_col} IN"
        f" (SELECT project_key FROM main.dim_zone_master WHERE zone_key IN {zones})"
    )


def _authorizer(action: int, arg1: str | None, _arg2: str | None, dbname: str | None, source: str | None) -> int:
    if action == sqlite3.SQLITE_READ and dbname == "main" and arg1 in SCOPED_TABLES and source is None:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def connect_scoped(path: str, scope: AuthorizedScope) -> sqlite3.Connection:
    """Read-only connection on which every scoped table only shows rows inside `scope`."""
    conn = connect_warehouse(path)
    conn.execute("PRAGMA query_only=OFF")  # temp views live in the in-memory temp schema; main stays mode=ro
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in sorted(SCOPED_TABLES & existing):
        name = quote_ident(table)
        conn.execute(f"CREATE TEMP VIEW {name} AS SELECT * FROM main.{name} WHERE {_predicate(table, scope)}")
    conn.execute("PRAGMA query_only=ON")
    conn.set_authorizer(_authorizer)
    return conn


def scoped_query(path: str, sql: str, scope: AuthorizedScope, *, timeout_s: float, count_hidden: bool = False) -> tuple[QueryResult, int | None]:
    """Run one SELECT inside `scope`; with `count_hidden`, also count the rows the scope removed (numbers only)."""
    statement = check_select(sql).rstrip().rstrip(";")
    with closing(connect_scoped(path, scope)) as conn:
        result = execute_select(conn, statement, timeout_s=timeout_s)
        if not count_hidden:
            return result, None
        with _deadline(conn, timeout_s):
            visible = conn.execute(f"SELECT COUNT(*) FROM ({statement})").fetchone()[0]
    with closing(connect_warehouse(path)) as conn, _deadline(conn, timeout_s):
        total = conn.execute(f"SELECT COUNT(*) FROM ({statement})").fetchone()[0]
    return result, total - visible


def scoped_tables(path: str, scope: AuthorizedScope, *, timeout_s: float) -> list[dict[str, Any]]:
    with closing(connect_scoped(path, scope)) as conn, _deadline(conn, timeout_s):
        names = [r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'table' ORDER BY name")]
        return [{"name": n, "row_count": conn.execute(f"SELECT COUNT(*) FROM {quote_ident(n)}").fetchone()[0]} for n in names]


def scoped_describe(path: str, table: str, scope: AuthorizedScope, *, timeout_s: float, sample_rows: int = 5) -> dict[str, Any]:
    with closing(connect_scoped(path, scope)) as conn, _deadline(conn, timeout_s):
        found = conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE", (table,)
        ).fetchone()
        if found is None:
            raise SqlError(f"table not found: {table}")
        name = quote_ident(found[0])
        columns = [{"name": r[1], "type": r[2]} for r in conn.execute(f"PRAGMA main.table_info({name})")]
        sample = conn.execute(f"SELECT * FROM {name} LIMIT ?", (sample_rows,)).fetchall()
    return {"table": found[0], "columns": columns, "sample_rows": [[_json_value(v) for v in row] for row in sample]}
