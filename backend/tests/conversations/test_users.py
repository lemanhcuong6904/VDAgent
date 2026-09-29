"""The users repository."""

from __future__ import annotations

from pathlib import Path

from conftest import migrated_database
from vdagent_backend.conversations import Users


async def test_ensure_adds_missing_users_and_leaves_existing_ones_alone(tmp_path: Path) -> None:
    db = await migrated_database(str(tmp_path / "backend.db"))
    users = Users(db)
    carol = await users.create_user("Carol")

    total = await users.ensure([("u_000000000001", "Alice"), (carol["id"], "Renamed")])
    assert total == 2
    assert await users.ensure([("u_000000000001", "Alice")]) == 2

    assert {(u["id"], u["name"]) for u in await users.list_users()} == {("u_000000000001", "Alice"), (carol["id"], "Carol")}
    await db.dispose()
