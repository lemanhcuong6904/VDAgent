"""The `users` table."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.core import new_id, utcnow
from vdagent_backend.persistence import Row, fetch_all, fetch_one, tables, upsert, write_returning

_users = tables.users


class Users:
    """Repository of users."""

    def __init__(self, db: AsyncEngine) -> None:
        self._db = db

    async def list_users(self) -> list[Row]:
        return await fetch_all(self._db, select(_users).order_by(_users.c.created_at, _users.c.id))

    async def get_user(self, user_id: str) -> Row | None:
        return await fetch_one(self._db, select(_users).where(_users.c.id == user_id))

    async def create_user(self, name: str) -> Row:
        row = await write_returning(self._db, _users.insert().values(id=new_id("u"), name=name).returning(_users))
        assert row is not None
        return row

    async def ensure(self, users: Iterable[tuple[str, str]]) -> int:
        """Insert the `(id, name)` users that do not exist yet (existing ones are left as they are).

        Returns:
            The total number of users afterwards.
        """
        now = utcnow()
        rows = [{"id": user_id, "name": name, "created_at": now} for user_id, name in users]
        async with self._db.begin() as conn:
            if rows:
                await conn.execute(upsert(self._db, _users).values(rows).on_conflict_do_nothing())
            return (await conn.execute(select(func.count()).select_from(_users))).scalar_one()
