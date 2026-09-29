"""Schema migrations: bring a database to the Alembic head, adopting pre-Alembic databases in place.

A database that has a `users` table but no `alembic_version` was created by the old
`CREATE TABLE IF NOT EXISTS` schema, which equals revision `0001`: it is stamped `0001` first,
then upgraded like any other. A database without `users` is treated as fresh.

`migrate` is synchronous (it runs its own event loop); call it before the app serves requests,
from a worker thread when an event loop is already running.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect, make_url
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE = "0001"


def alembic_config(url: str) -> Config:
    """An Alembic config for the package migrations against `url` (an async SQLAlchemy URL)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Alembic filter: skip the SQLite full-text index tables, which the metadata does not declare."""
    return not (type_ == "table" and name is not None and name.startswith("memories_fts"))


def migrate(url: str) -> None:
    """Upgrade the database at `url` to the head revision (creating it if needed)."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_migrate(url))


async def _migrate(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_upgrade, alembic_config(url))
    finally:
        await engine.dispose()


def _upgrade(conn: Connection, cfg: Config) -> None:
    tables = set(inspect(conn).get_table_names())
    cfg.attributes["connection"] = conn
    if "users" in tables and "alembic_version" not in tables:
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
