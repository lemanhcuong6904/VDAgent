"""The async database engine and its per-dialect connection setup.

`create_database(url)` only builds the `AsyncEngine`; it opens no connection and applies no schema
(`migrate` does that). SQLite connections get WAL, foreign keys, a 5 s busy timeout and the
sqlite-vec extension (vector search over agent memory).
"""

from __future__ import annotations

from typing import Any

import sqlite_vec
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def sqlite_url(path: str) -> str:
    """The async SQLAlchemy URL of the SQLite file at `path`."""
    return f"sqlite+aiosqlite:///{path}"


def create_database(url: str) -> AsyncEngine:
    """An `AsyncEngine` for `url` with the dialect's connect hooks installed."""
    engine = create_async_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _sqlite_connect)
    return engine


def _sqlite_connect(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()
    dbapi_conn.run_async(_load_sqlite_vec)


async def _load_sqlite_vec(conn: Any) -> None:  # aiosqlite.Connection
    await conn.enable_load_extension(True)
    await conn.load_extension(sqlite_vec.loadable_path())
    await conn.enable_load_extension(False)
