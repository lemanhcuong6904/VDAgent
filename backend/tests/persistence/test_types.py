"""Dialect column types on SQLite: what is stored, what is read back."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.persistence import Embedding, Json, UtcTimestamp, create_database, sqlite_url

_md = sa.MetaData()
_probe = sa.Table(
    "probe",
    _md,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("at", UtcTimestamp),
    sa.Column("doc", Json),
    sa.Column("vec", Embedding),
)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_database(sqlite_url(str(tmp_path / "types.db")))
    async with engine.begin() as conn:
        await conn.run_sync(_md.create_all)
    yield engine
    await engine.dispose()


async def _raw(db: AsyncEngine, column: str) -> object:
    async with db.connect() as conn:
        return (await conn.exec_driver_sql(f"SELECT {column} FROM probe")).scalar_one()


async def _read(db: AsyncEngine) -> sa.RowMapping:
    async with db.connect() as conn:
        return (await conn.execute(sa.select(_probe))).mappings().one()


async def test_utc_timestamp_stores_microseconds_and_reads_milliseconds(db: AsyncEngine) -> None:
    async with db.begin() as conn:
        await conn.execute(_probe.insert().values(id=1, at=datetime(2026, 9, 29, 10, 4, 5, 123456, tzinfo=UTC)))
    assert await _raw(db, "at") == "2026-09-29T10:04:05.123456Z"
    assert (await _read(db))["at"] == "2026-09-29T10:04:05.123Z"


async def test_utc_timestamp_reads_legacy_millisecond_text_unchanged(db: AsyncEngine) -> None:
    async with db.begin() as conn:
        await conn.exec_driver_sql("INSERT INTO probe (id, at) VALUES (1, '2026-09-24T08:00:00.007Z')")
    assert (await _read(db))["at"] == "2026-09-24T08:00:00.007Z"


@pytest.mark.parametrize("value", [5, "5", [[1, "a", None]], {"k": [1.5]}, None])
async def test_json_round_trips_values_including_scalars(db: AsyncEngine, value: object) -> None:
    async with db.begin() as conn:
        await conn.execute(_probe.insert().values(id=1, doc=value))
    assert (await _read(db))["doc"] == value


async def test_embedding_is_stored_as_float32_blob_and_read_as_floats(db: AsyncEngine) -> None:
    async with db.begin() as conn:
        await conn.execute(_probe.insert().values(id=1, vec=[1.0, -0.5, 0.25]))
    assert len(await _raw(db, "vec")) == 12  # type: ignore[arg-type]
    assert (await _read(db))["vec"] == [1.0, -0.5, 0.25]
