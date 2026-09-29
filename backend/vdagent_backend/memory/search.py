"""Memory search, the one dialect-specific query module.

`MemorySearch` ranks one scope's notes by keywords or by an embedding; scores are "lower is
better" (the SDK `Note.score` contract). `SqliteMemorySearch` uses the `memories_fts` FTS5 index
(`bm25`) and sqlite-vec's `vec_distance_cosine` over the scope's notes of the query's dimension
(brute force, fine at PoC volumes), so agents may use embeddings of any dimension.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import sqlite_vec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from vdagent_sdk import Note

from vdagent_backend.persistence import UtcTimestamp

_WORD = re.compile(r"\w+")
_SCOPE = "m.user_id = :user_id AND m.agent = :agent"


@dataclass(frozen=True)
class Scope:
    """The (user, agent) pair whose notes a search may see."""

    user_id: str
    agent: str


class MemorySearch(Protocol):
    async def keyword(self, conn: AsyncConnection, scope: Scope, query: str, limit: int) -> list[Note]: ...

    async def vector(self, conn: AsyncConnection, scope: Scope, embedding: Sequence[float], limit: int) -> list[Note]: ...


def fts_query(query: str) -> str:
    """Free text → quoted, OR-ed FTS5 tokens, so user text can never be FTS syntax. `""` if no words."""
    return " OR ".join(f'"{word}"' for word in _WORD.findall(query))


async def _notes(conn: AsyncConnection, sql: str, scope: Scope, **params: Any) -> list[Note]:
    stmt = text(sql).columns(created_at=UtcTimestamp())  # API timestamp format, like every other read
    res = await conn.execute(stmt, {"user_id": scope.user_id, "agent": scope.agent, **params})
    return [Note(**row) for row in res.mappings().all()]


class SqliteMemorySearch:
    async def keyword(self, conn: AsyncConnection, scope: Scope, query: str, limit: int) -> list[Note]:
        match = fts_query(query)
        if not match:
            return []
        return await _notes(
            conn,
            "SELECT m.id, m.kind, m.text, m.created_at, bm25(memories_fts) AS score "
            "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
            f"WHERE memories_fts MATCH :match AND {_SCOPE} ORDER BY score, m.id DESC LIMIT :limit",
            scope,
            match=match,
            limit=limit,
        )

    async def vector(self, conn: AsyncConnection, scope: Scope, embedding: Sequence[float], limit: int) -> list[Note]:
        return await _notes(
            conn,
            "SELECT m.id, m.kind, m.text, m.created_at, vec_distance_cosine(m.embedding, :q) AS score "
            f"FROM memories m WHERE {_SCOPE} AND m.embedding IS NOT NULL AND vec_length(m.embedding) = :dim "
            "ORDER BY score, m.id DESC LIMIT :limit",
            scope,
            q=sqlite_vec.serialize_float32(list(embedding)),
            dim=len(embedding),
            limit=limit,
        )
