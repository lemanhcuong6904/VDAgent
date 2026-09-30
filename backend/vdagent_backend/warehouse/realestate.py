"""`RealEstateWarehouse`: the async face of the user-scoped, read-only SQL over the real-estate DW (`re_sql.py`).

Every call takes the caller's `AuthorizedScope` (from `scopes`, never from a message): rows outside it are neither
returned nor counted (WS7 F-08).
"""

from __future__ import annotations

import asyncio
from typing import Any

from vdagent_backend.warehouse import re_sql
from vdagent_backend.warehouse.sql import SQL_TIMEOUT_S, QueryResult
from vdagent_contracts.scope import AuthorizedScope


class RealEstateWarehouse:
    """The real-estate DW mock at `path`, opened read-only and scoped per call; every statement gets `timeout_s`."""

    def __init__(self, path: str, timeout_s: float = SQL_TIMEOUT_S) -> None:
        self._path = path
        self._timeout_s = timeout_s

    async def tables(self, scope: AuthorizedScope) -> list[dict[str, Any]]:
        """`[{name, row_count}]`, counting only the rows inside `scope`."""
        return await asyncio.to_thread(re_sql.scoped_tables, self._path, scope, timeout_s=self._timeout_s)

    async def describe(self, table: str, scope: AuthorizedScope, sample_rows: int = 5) -> dict[str, Any]:
        """`{table, columns, sample_rows}` with sample rows inside `scope`. Raises `SqlError`."""
        return await asyncio.to_thread(
            re_sql.scoped_describe, self._path, table, scope, timeout_s=self._timeout_s, sample_rows=sample_rows
        )

    async def query(self, statement: str, scope: AuthorizedScope) -> QueryResult:
        """Run one SELECT inside `scope`. Raises `SqlError`."""
        return await asyncio.to_thread(re_sql.scoped_query, self._path, statement, scope, timeout_s=self._timeout_s)
