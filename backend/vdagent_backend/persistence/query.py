"""Run Core statements and get plain dicts keyed by column name.

Reads open a connection; writes run in their own transaction. Multi-statement transactions use
`db.begin()` directly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Executable, Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncEngine

Row = dict[str, Any]


async def fetch_all(db: AsyncEngine, stmt: Executable) -> list[Row]:
    async with db.connect() as conn:
        return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def fetch_one(db: AsyncEngine, stmt: Executable) -> Row | None:
    """The first row, or None."""
    async with db.connect() as conn:
        row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row is not None else None


async def write_returning(db: AsyncEngine, stmt: Executable) -> Row | None:
    """Run a `… RETURNING` write in its own transaction; the returned row, or None if none matched."""
    async with db.begin() as conn:
        row = (await conn.execute(stmt)).mappings().one_or_none()
    return dict(row) if row is not None else None


async def write_returning_all(db: AsyncEngine, stmt: Executable) -> list[Row]:
    """Run a `… RETURNING` write in its own transaction; every returned row."""
    async with db.begin() as conn:
        return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


def upsert(db: AsyncEngine, table: Table) -> sqlite.Insert | postgresql.Insert:
    """An INSERT for `table` that supports `on_conflict_do_nothing` / `on_conflict_do_update`."""
    return postgresql.insert(table) if db.dialect.name == "postgresql" else sqlite.insert(table)
