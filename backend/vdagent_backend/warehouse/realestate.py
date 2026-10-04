"""`RealEstateWarehouse`: the async face of the user-scoped, read-only SQL over the real-estate DW (`re_sql.py`).

Every call takes the caller's `AuthorizedScope` (from `scopes`, never from a message): rows outside it are neither
returned nor counted (WS7 F-08).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from vdagent_backend.warehouse import re_pg, re_sql
from vdagent_backend.warehouse.sql import SQL_TIMEOUT_S, QueryResult
from vdagent_contracts.scope import AuthorizedScope


VAR = "VDAGENT_RE_WAREHOUSE_DB"
_PG_SCHEMES = ("postgresql://", "postgres://")


class ReWarehouseConfigError(ValueError):
    """The real-estate DW setting is missing or malformed; the message names `VDAGENT_RE_WAREHOUSE_DB`, never a
    credential. Raised at construction, so the Backend does not start on it."""


def _check(path: str) -> str:
    """`path` when it names a warehouse explicitly: a `postgresql://` DSN with host and database, or a file path (the
    synthetic SQLite mock). Anything else is refused; nothing ever falls back to the mock."""
    value = path.strip()
    if not value:
        raise ReWarehouseConfigError(
            f"{VAR} is not set: give the real warehouse DSN (postgresql://<user>:<password>@<host>:<port>/<database>), "
            f"or, for tests and offline work only, the explicit path of the SQLite mock (e.g. ./var/re_warehouse.db).")
    if value.startswith(_PG_SCHEMES):
        url = urlsplit(value)
        if not url.hostname or not url.path.lstrip("/"):
            raise ReWarehouseConfigError(f"{VAR} is a malformed PostgreSQL DSN: it needs a host and a database "
                                         "(postgresql://<user>:<password>@<host>:<port>/<database>).")
    elif "://" in value:
        scheme = value.split("://", 1)[0]
        raise ReWarehouseConfigError(f"{VAR} uses the unsupported scheme {scheme!r}: use postgresql:// for the real "
                                     "warehouse, or a plain file path for the SQLite mock.")
    return value


class RealEstateWarehouse:
    """The real-estate DW at `path`, opened read-only and scoped per call; every statement gets `timeout_s`.

    `path` is a `postgresql://` DSN for the DATA team's real warehouse (`re_pg`), or the path of the synthetic SQLite
    mock, named explicitly. A missing or malformed value raises `ReWarehouseConfigError`.
    """

    def __init__(self, path: str, timeout_s: float = SQL_TIMEOUT_S) -> None:
        path = _check(path)
        self._path = path
        self._timeout_s = timeout_s
        self._reader = re_pg if path.startswith(_PG_SCHEMES) else re_sql

    @property
    def source(self) -> dict[str, Any]:
        """Which backend serves this DW and where, never with credentials: `{backend: postgresql, host, port, database}`
        or `{backend: sqlite, file}` (the synthetic mock). Agents derive their source labels from it."""
        if self._reader is re_pg:
            url = urlsplit(self._path)
            return {"backend": "postgresql", "host": url.hostname, "port": url.port or 5432, "database": url.path.lstrip("/")}
        return {"backend": "sqlite", "file": Path(self._path).name}

    async def tables(self, scope: AuthorizedScope) -> list[dict[str, Any]]:
        """`[{name, row_count}]`, counting only the rows inside `scope`."""
        return await asyncio.to_thread(self._reader.scoped_tables, self._path, scope, timeout_s=self._timeout_s)

    async def describe(self, table: str, scope: AuthorizedScope, sample_rows: int = 5) -> dict[str, Any]:
        """`{table, columns, sample_rows}` with sample rows inside `scope`. Raises `SqlError`."""
        return await asyncio.to_thread(
            self._reader.scoped_describe, self._path, table, scope, timeout_s=self._timeout_s, sample_rows=sample_rows
        )

    async def query(self, statement: str, scope: AuthorizedScope) -> QueryResult:
        """Run one SELECT inside `scope`. Raises `SqlError`."""
        return await asyncio.to_thread(self._reader.scoped_query, self._path, statement, scope, timeout_s=self._timeout_s)


def startup_lines(source: dict[str, Any]) -> list[str]:
    """The log lines that say, at startup, which warehouse the Backend reads (no credentials)."""
    if source["backend"] == "postgresql":
        return ["Warehouse backend: PostgreSQL", f"Warehouse source: {source['host']}:{source['port']}/{source['database']}"]
    return ["Warehouse backend: SQLite (synthetic mock)", f"Warehouse source: {source['file']}"]
