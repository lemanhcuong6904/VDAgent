"""Alembic environment for the Backend database.

`migrate()` passes its open connection in `config.attributes["connection"]`. From the CLI
(`uv run alembic -c backend/alembic.ini …`) the URL comes from `-x url=<async url>` or
`sqlalchemy.url` in `alembic.ini`, and an async engine is created here.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from vdagent_backend.persistence.migrate import include_name
from vdagent_backend.persistence.tables import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _run(conn: Connection) -> None:
    context.configure(
        connection=conn,
        target_metadata=metadata,
        include_name=include_name,
        render_as_batch=conn.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_run)
            await conn.commit()
    finally:
        await engine.dispose()


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("no database URL: pass -x url=sqlite+aiosqlite:///<path>")
    return url


if context.is_offline_mode():
    raise RuntimeError("offline (--sql) migrations are not supported")

connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    asyncio.run(_run_async(_url()))
