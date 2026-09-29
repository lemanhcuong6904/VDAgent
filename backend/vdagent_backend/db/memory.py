"""Agent memory (agent-freedom spec §2): notes of one (user_id, agent) scope.

`ScopedMemory` implements the SDK's `Memory` for `ctx.memory`. The scope is fixed at construction;
every query filters on it. Keyword search uses the `memories_fts` FTS5 index; vector search ranks
with sqlite-vec's `vec_distance_cosine` over this scope's notes of the same dimension (brute force,
fine at PoC volumes), so agents may use embeddings of any dimension.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import sqlite_vec
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncEngine
from vdagent_sdk import Note

_WORD = re.compile(r"\w+")
_SCOPE = "m.user_id = :user_id AND m.agent = :agent"


def fts_query(query: str) -> str:
    """Free text → quoted, OR-ed FTS5 tokens, so user text can never be FTS syntax. `""` if no words."""
    return " OR ".join(f'"{word}"' for word in _WORD.findall(query))


class ScopedMemory:
    def __init__(self, db: AsyncEngine, user_id: str, agent: str) -> None:
        self._db = db
        self._scope = {"user_id": user_id, "agent": agent}

    async def _rows(self, query: str, **params: Any) -> list[Note]:
        async with self._db.connect() as conn:
            res = await conn.execute(sql(query), {**self._scope, **params})
            return [Note(**row) for row in res.mappings().all()]

    async def save(self, text: str, kind: str = "note", embedding: Sequence[float] | None = None) -> int:
        if not text.strip():
            raise ValueError("memory.save: text must be non-empty")
        if not kind.strip():
            raise ValueError("memory.save: kind must be non-empty")
        if embedding is not None and len(embedding) == 0:
            raise ValueError("memory.save: embedding must be non-empty (or None)")
        blob = sqlite_vec.serialize_float32(list(embedding)) if embedding is not None else None
        async with self._db.begin() as conn:
            res = await conn.execute(
                sql(
                    "INSERT INTO memories (user_id, agent, kind, text, embedding) "
                    "VALUES (:user_id, :agent, :kind, :text, :embedding)"
                ),
                {**self._scope, "kind": kind, "text": text, "embedding": blob},
            )
            return int(res.lastrowid)  # type: ignore[attr-defined]

    async def search(self, query: str, limit: int = 5, embedding: Sequence[float] | None = None) -> list[Note]:
        if embedding is not None:
            return await self._rows(
                "SELECT m.id, m.kind, m.text, m.created_at, vec_distance_cosine(m.embedding, :q) AS score "
                f"FROM memories m WHERE {_SCOPE} AND m.embedding IS NOT NULL AND vec_length(m.embedding) = :dim "
                "ORDER BY score, m.id DESC LIMIT :limit",
                q=sqlite_vec.serialize_float32(list(embedding)),
                dim=len(embedding),
                limit=limit,
            )
        match = fts_query(query)
        if not match:
            return []
        return await self._rows(
            "SELECT m.id, m.kind, m.text, m.created_at, bm25(memories_fts) AS score "
            f"FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
            f"WHERE memories_fts MATCH :match AND {_SCOPE} ORDER BY score, m.id DESC LIMIT :limit",
            match=match,
            limit=limit,
        )

    async def recent(self, limit: int = 10) -> list[Note]:
        return await self._rows(
            f"SELECT m.id, m.kind, m.text, m.created_at FROM memories m WHERE {_SCOPE} ORDER BY m.id DESC LIMIT :limit",
            limit=limit,
        )

    async def delete(self, note_id: int) -> bool:
        async with self._db.begin() as conn:
            res = await conn.execute(
                sql("DELETE FROM memories WHERE id = :id AND user_id = :user_id AND agent = :agent"),
                {**self._scope, "id": note_id},
            )
            return res.rowcount > 0  # type: ignore[attr-defined]
