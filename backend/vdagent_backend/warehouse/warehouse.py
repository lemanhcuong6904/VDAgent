"""`Warehouse`: the async face of the read-only SQL in `sql.py` (the only place that uses threads)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from vdagent_backend.warehouse import sql
from vdagent_backend.warehouse.sql import QueryResult


class Warehouse:
    """The analytics warehouse at `path`, opened read-only per call; every statement gets `timeout_s`."""

    def __init__(self, path: str, timeout_s: float = sql.SQL_TIMEOUT_S) -> None:
        self._path = path
        self._timeout_s = timeout_s

    async def tables(self) -> list[dict[str, Any]]:
        """`[{name, row_count}]` for every table."""
        return await asyncio.to_thread(sql.warehouse_tables, self._path, timeout_s=self._timeout_s)

    async def describe(self, table: str) -> dict[str, Any]:
        """`{table, columns: [{name, type}], sample_rows}` (case-insensitive name). Raises `SqlError`."""
        return await asyncio.to_thread(sql.warehouse_describe, self._path, table, timeout_s=self._timeout_s)

    async def query(self, statement: str) -> QueryResult:
        """Run one SELECT on the warehouse. Raises `SqlError`."""
        return await asyncio.to_thread(sql.warehouse_query, self._path, statement, timeout_s=self._timeout_s)

    async def query_datasets(self, statement: str, datasets: Sequence[dict[str, Any]]) -> QueryResult:
        """Run one SELECT over `datasets` (each a table named by its id). Raises `SqlError`."""
        return await asyncio.to_thread(sql.datasets_query, statement, datasets, timeout_s=self._timeout_s)
