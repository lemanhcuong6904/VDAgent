"""Read-only, user-scoped SQL over the real-estate DW in PostgreSQL (the `re_*` tools over the DATA team's warehouse).

The DATA team's warehouse lives in schema `gold`; the canonical read layer `re` (docker/warehouse/canonical_views.sql)
shows it in the shape the agents already read. The Backend connects as `vdagent_reader`, which can read `re` only and
only in read-only transactions. On top of that, like `re_sql` does for SQLite:

* a query is one SELECT over the canonical tables, unqualified (no `gold.x`, `re.x`, catalogs, table functions);
* every scoped table is shadowed, per connection, by a TEMP VIEW of the same name that keeps only the rows inside the
  caller's `authorized_scope` (`search_path` starts with `pg_temp`), so even a query that forgot its own RBAC filter
  cannot see rows outside the scope, and cannot even count them (WS7 F-08).

Blocking psycopg code: callers run it in a worker thread.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterable
from contextlib import closing
from decimal import Decimal
from typing import Any

import psycopg
import sqlglot
from psycopg import sql as pgsql
from sqlglot import exp
from sqlglot.errors import SqlglotError

from vdagent_backend.warehouse.sql import (
    MAX_ROWS,
    QueryResult,
    SqlError,
    _column_type,  # pyright: ignore[reportPrivateUsage]
    _unique_names,  # pyright: ignore[reportPrivateUsage]
)
from vdagent_contracts.scope import AuthorizedScope

# table → (project column, zone column or None); every canonical table carries its keys as TEXT
_BY_PROJECT: dict[str, tuple[str, str | None]] = {
    "dim_project_profile": ("project_key", None),
    "dim_zone_master": ("project_key", "zone_key"),
    "dim_unit_master": ("project_key", "zone_key"),
    "fact_unit_inventory_snapshot": ("project_key", "zone_key"),
    "fact_sales_channel_performance": ("project_key", None),
    "dim_secondary_market_comps": ("project_key", None),
    "dim_infrastructure_assets": ("project_key", None),
}
# tables keyed by unit only: scoped through the units the caller may see
_BY_UNIT = ("fact_unit_price_history", "fact_sales_funnel_daily", "dm_unit_friction_diagnostics", "unit_diagnostic_causes")
# not scoped: shared reference data
_OPEN = ("snapshot_manifest", "semantic_config", "dim_sales_channel", "fact_market_macro_monthly")
TABLES = tuple(sorted((*_BY_PROJECT, *_BY_UNIT, *_OPEN)))

CONNECT_ATTEMPTS = 3
CONNECT_TIMEOUT_S = 5
_RETRY_DELAY_S = 0.5  # × attempt number

_DENIED_STATEMENTS =(exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Into, exp.Create, exp.Drop, exp.Alter, exp.Command)
_DENIED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "query_to_xml", "cursor_to_xml", "table_to_xml",
                             "schema_to_xml", "database_to_xml")


def check_query(sql: str) -> str:
    """The statement to run: exactly one SELECT / WITH … SELECT over unqualified canonical tables (`SqlError` otherwise)."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise SqlError(f"not a valid SQL statement: {str(exc).splitlines()[0]}") from None
    if not statements:
        raise SqlError("empty SQL statement")
    if len(statements) != 1:
        raise SqlError("exactly one SQL statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, exp.Select | exp.Union) or stmt.find(*_DENIED_STATEMENTS) is not None:
        raise SqlError("only a single read-only SELECT (or WITH … SELECT) statement is allowed")
    ctes = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SqlError("table functions are not allowed")
        if table.db or table.catalog:
            raise SqlError(f"schema-qualified table names are not allowed: {table.sql()}")
        if table.name not in ctes and table.name not in TABLES:
            raise SqlError(f"table not allowed: {table.name}; use one of: {', '.join(TABLES)}")
    for func in stmt.find_all(exp.Func):
        name = (func.name or func.key).lower()
        if name.startswith(_DENIED_FUNCTION_PREFIXES):
            raise SqlError(f"function not allowed: {name}")
    return sql.strip().rstrip(";").rstrip()


def _literals(values: Iterable[str]) -> pgsql.Composable:
    items = [pgsql.Literal(v) for v in values]
    return pgsql.SQL(", ").join(items) if items else pgsql.SQL("NULL")


def _predicate(table: str, scope: AuthorizedScope) -> pgsql.Composable:
    projects, zones = _literals(scope.project_ids), _literals(scope.zone_ids)
    if table in _BY_UNIT:
        return pgsql.SQL(
            "unit_key IN (SELECT unit_key FROM re.unit_scope WHERE project_key IN ({p}) OR zone_key IN ({z}))"
        ).format(p=projects, z=zones)
    project_col, zone_col = _BY_PROJECT[table]
    if zone_col is not None:
        return pgsql.SQL("{pc} IN ({p}) OR {zc} IN ({z})").format(
            pc=pgsql.Identifier(project_col), zc=pgsql.Identifier(zone_col), p=projects, z=zones)
    # project-level tables: projects granted whole, or holding a granted zone
    return pgsql.SQL("{pc} IN ({p}) OR {pc} IN (SELECT project_key FROM re.dim_zone_master WHERE zone_key IN ({z}))").format(
        pc=pgsql.Identifier(project_col), p=projects, z=zones)


def _open(dsn: str) -> psycopg.Connection[Any]:
    """A new connection; a remote warehouse (AWS RDS) drops some attempts, so a failed attempt is retried."""
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return psycopg.connect(dsn, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S)
        except psycopg.OperationalError as exc:
            if attempt == CONNECT_ATTEMPTS:
                raise SqlError(f"warehouse unavailable: {type(exc).__name__}") from None
            time.sleep(_RETRY_DELAY_S * attempt)
        except psycopg.Error as exc:
            raise SqlError(f"warehouse unavailable: {type(exc).__name__}") from None
    raise AssertionError("unreachable")


def _connect(dsn: str, scope: AuthorizedScope, timeout_s: float) -> psycopg.Connection[Any]:
    """A connection on which every scoped table only shows rows inside `scope`, then locked read-only.
    The whole setup goes in one round trip: over a WAN every statement costs a network round trip."""
    conn = _open(dsn)
    setup = [
        pgsql.SQL("SET TRANSACTION READ WRITE"),  # TEMP views are DDL; the batch is one implicit transaction, begun read-only
        *(pgsql.SQL("CREATE TEMP VIEW {t} AS SELECT * FROM re.{t} WHERE {pred}").format(
            t=pgsql.Identifier(table), pred=_predicate(table, scope)) for table in (*_BY_PROJECT, *_BY_UNIT)),
        pgsql.SQL("SET default_transaction_read_only = on"),
        pgsql.SQL("SET statement_timeout = {ms}").format(ms=pgsql.Literal(max(1, int(timeout_s * 1000)))),
    ]
    try:
        # no parameters, so psycopg sends the statements as one simple query
        conn.execute(";\n".join(s.as_string(None) for s in setup))  # pyright: ignore[reportArgumentType]
    except psycopg.Error as exc:
        conn.close()
        raise SqlError(f"warehouse unavailable: {type(exc).__name__}") from None
    return conn


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)  # decimals travel as strings: no float ever reaches an artifact
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    return value


def _run(conn: psycopg.Connection[Any], statement: str | pgsql.Composable, timeout_s: float, limit: int) -> tuple[list[str], list[list[Any]], bool]:
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(statement)  # pyright: ignore[reportArgumentType]
            names = [d.name for d in cur.description or []]
            fetched = cur.fetchmany(limit + 1)
    except psycopg.errors.QueryCanceled:
        raise SqlError(f"query exceeded the {timeout_s:g} s time limit") from None
    except psycopg.Error as exc:
        raise SqlError(str(exc).splitlines()[0]) from None
    rows = [[_json_value(v) for v in row] for row in fetched[:limit]]
    return names, rows, len(fetched) > limit


def scoped_query(dsn: str, sql: str, scope: AuthorizedScope, *, timeout_s: float) -> QueryResult:
    """Run one SELECT inside `scope`. Rows outside the scope are neither returned nor counted (WS7 F-08)."""
    statement = check_query(sql)
    with closing(_connect(dsn, scope, timeout_s)) as conn:
        names, rows, truncated = _run(conn, statement, timeout_s, MAX_ROWS)
    columns = [{"name": name, "type": _column_type(rows, i)} for i, name in enumerate(_unique_names(names))]
    return QueryResult(columns=columns, rows=rows, truncated=truncated)


def scoped_tables(dsn: str, scope: AuthorizedScope, *, timeout_s: float) -> list[dict[str, Any]]:
    """`[{name, row_count}]` of every canonical table, counting only the rows inside `scope`."""
    with closing(_connect(dsn, scope, timeout_s)) as conn:
        out: list[dict[str, Any]] = []
        for table in TABLES:
            _, rows, _ = _run(conn, pgsql.SQL("SELECT count(*) FROM {t}").format(t=pgsql.Identifier(table)), timeout_s, 1)
            out.append({"name": table, "row_count": rows[0][0]})
        return out


def scoped_describe(dsn: str, table: str, scope: AuthorizedScope, *, timeout_s: float, sample_rows: int = 5) -> dict[str, Any]:
    """`{table, columns, sample_rows}` with sample rows inside `scope`. Raises `SqlError` for an unknown table."""
    found = next((t for t in TABLES if t == table.lower()), None)
    if found is None:
        raise SqlError(f"table not found: {table}")
    with closing(_connect(dsn, scope, timeout_s)) as conn:
        _, columns, _ = _run(
            conn,
            pgsql.SQL("SELECT column_name, upper(data_type) FROM information_schema.columns WHERE table_schema = 're'"
                      " AND table_name = {t} ORDER BY ordinal_position").format(t=pgsql.Literal(found)),
            timeout_s, 1000)
        _, sample, _ = _run(conn, pgsql.SQL("SELECT * FROM {t} LIMIT {n}").format(t=pgsql.Identifier(found), n=pgsql.Literal(sample_rows)),
                            timeout_s, max(sample_rows, 1))
    return {"table": found, "columns": [{"name": n, "type": t} for n, t in columns], "sample_rows": sample[:sample_rows]}
