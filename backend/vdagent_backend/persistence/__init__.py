"""Persistence: the database engine, the table metadata, dialect types, query helpers and migrations.

Repositories in the domain packages build Core statements over `tables` and run them with the
query helpers. Only `memory` search and dialect-gated migrations use raw SQL.

May import: `core`.
"""

from vdagent_backend.persistence import tables
from vdagent_backend.persistence.database import create_database, sqlite_url
from vdagent_backend.persistence.migrate import migrate
from vdagent_backend.persistence.query import Row, fetch_all, fetch_one, upsert, write_returning, write_returning_all
from vdagent_backend.persistence.types import Embedding, Json, UtcTimestamp

__all__ = [
    "Embedding",
    "Json",
    "Row",
    "UtcTimestamp",
    "create_database",
    "fetch_all",
    "fetch_one",
    "migrate",
    "sqlite_url",
    "tables",
    "upsert",
    "write_returning",
    "write_returning_all",
]
