"""Column types whose storage depends on the dialect; Python always sees the same values.

| Type | SQLite | PostgreSQL | Python value |
|---|---|---|---|
| `UtcTimestamp` | TEXT `…SS.ffffffZ` | `timestamptz` | bind an aware `datetime`; read `str` `…SS.mmmZ` |
| `Json` | TEXT (`json.dumps`/`loads`) | `JSONB` | any JSON-able value; `None` is SQL NULL |
| `Embedding` | BLOB of float32 (sqlite-vec) | pgvector, added with PostgreSQL | `list[float]` |

`Json` is a TEXT decorator rather than SQLAlchemy `JSON`: SQLite gives a column declared `JSON`
NUMERIC affinity, which would turn a stored scalar like `"5"` into the integer 5.
"""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from typing import Any

import sqlite_vec
from sqlalchemy import LargeBinary, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine

from vdagent_backend.core import iso_ms


class UtcTimestamp(TypeDecorator[str]):
    """A UTC instant. Written from an aware `datetime`, read as the API text `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    SQLite keeps microseconds so rows written in the same millisecond still order correctly; rows
    written before this type (millisecond text) read back unchanged.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.TIMESTAMP(timezone=True))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError(f"UtcTimestamp needs an aware datetime, got {value!r}")
        if dialect.name == "sqlite":
            return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return iso_ms(moment if moment.tzinfo else moment.replace(tzinfo=UTC))


class Json(TypeDecorator[Any]):
    """Any JSON-able value."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None or dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None or dialect.name == "postgresql":
            return value
        return json.loads(value)


class Embedding(TypeDecorator[list[float]]):
    """A float vector of any dimension, stored as sqlite-vec float32 (little-endian) on SQLite."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> bytes | None:
        return None if value is None else sqlite_vec.serialize_float32(list(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        return list(struct.unpack(f"<{len(value) // 4}f", value))
