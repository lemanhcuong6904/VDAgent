"""`ScopedMemory`: the SDK `Memory` behind `ctx.memory`, fixed to one (user, agent) scope.

Every query filters on the scope (user isolation); a note id from another scope reads and deletes
like an unknown id. Search is delegated to the dialect's `MemorySearch`.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine
from vdagent_sdk import Note

from vdagent_backend.memory.search import MemorySearch, Scope, SqliteMemorySearch
from vdagent_backend.persistence import fetch_all, tables, write_returning

_memories = tables.memories


def _search_for(db: AsyncEngine) -> MemorySearch:
    if db.dialect.name == "sqlite":
        return SqliteMemorySearch()
    raise NotImplementedError(f"memory search is not implemented for {db.dialect.name}")


class ScopedMemory:
    """The SDK `Memory` of one (user, agent) scope."""

    def __init__(self, db: AsyncEngine, user_id: str, agent: str) -> None:
        self._db = db
        self._scope = Scope(user_id, agent)
        self._search = _search_for(db)

    def _in_scope(self):  # noqa: ANN202  (a SQL boolean clause)
        return (_memories.c.user_id == self._scope.user_id) & (_memories.c.agent == self._scope.agent)

    async def save(self, text: str, kind: str = "note", embedding: Sequence[float] | None = None) -> int:
        if not text.strip():
            raise ValueError("memory.save: text must be non-empty")
        if not kind.strip():
            raise ValueError("memory.save: kind must be non-empty")
        if embedding is not None and len(embedding) == 0:
            raise ValueError("memory.save: embedding must be non-empty (or None)")
        row = await write_returning(
            self._db,
            _memories.insert()
            .values(user_id=self._scope.user_id, agent=self._scope.agent, kind=kind, text=text, embedding=embedding)
            .returning(_memories.c.id),
        )
        assert row is not None
        return row["id"]

    async def search(self, query: str, limit: int = 5, embedding: Sequence[float] | None = None) -> list[Note]:
        async with self._db.connect() as conn:
            if embedding is not None:
                return await self._search.vector(conn, self._scope, embedding, limit)
            return await self._search.keyword(conn, self._scope, query, limit)

    async def recent(self, limit: int = 10) -> list[Note]:
        rows = await fetch_all(
            self._db,
            select(_memories.c.id, _memories.c.kind, _memories.c.text, _memories.c.created_at)
            .where(self._in_scope())
            .order_by(_memories.c.id.desc())
            .limit(limit),
        )
        return [Note(**row) for row in rows]

    async def delete(self, note_id: int) -> bool:
        async with self._db.begin() as conn:
            res = await conn.execute(delete(_memories).where(_memories.c.id == note_id, self._in_scope()))
            return res.rowcount > 0
