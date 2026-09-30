"""The artifacts repository: datasets stored row by row, read by page or in bulk, owner-scoped."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from conftest import ALICE, BOB, NOW, migrated_database, seed_users
from vdagent_backend.artifacts import Artifacts

COLUMNS = [{"name": "n", "type": "INTEGER"}, {"name": "s", "type": "TEXT"}]
ROWS = [[i, f"r{i}"] for i in range(5)]


@pytest.fixture
async def repo(tmp_path: Path) -> AsyncIterator[Artifacts]:
    path = str(tmp_path / "backend.db")
    db = await migrated_database(path)
    seed_users(path)
    async with db.begin() as conn:
        for user in (ALICE, BOB):
            await conn.exec_driver_sql(
                "INSERT INTO tasks (id, user_id, root_agent, status, created_at) VALUES (?, ?, 'data', 'running', ?)",
                (f"t_{user}", user, NOW),
            )
            await conn.exec_driver_sql(
                "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                " VALUES (?, ?, ?, 'data', 'user', 0, 'x', 'running', ?)",
                (f"inv_{user}", f"t_{user}", user, NOW),
            )
    yield Artifacts(db)
    await db.dispose()


async def _dataset(repo: Artifacts, user: str = ALICE, rows: list[list[object]] = ROWS) -> str:
    return await repo.insert_dataset(
        user_id=user, invocation_id=f"inv_{user}", name="n", source_sql="SELECT n", columns=COLUMNS, rows=rows, truncated=False
    )


@pytest.mark.parametrize(
    ("offset", "limit", "expected"),
    [(0, 2, ROWS[:2]), (3, 10, ROWS[3:]), (4, 1, ROWS[4:]), (5, 3, []), (9, 1, [])],
    ids=["first-page", "past-the-end", "last-row", "at-row-count", "beyond"],
)
async def test_get_rows_returns_the_page_in_order(repo: Artifacts, offset: int, limit: int, expected: list[list[object]]) -> None:
    ds = await _dataset(repo)
    assert await repo.get_rows(ALICE, ds, offset, limit) == expected


async def test_another_user_reads_nothing(repo: Artifacts) -> None:
    ds = await _dataset(repo)
    assert await repo.get_dataset_meta(BOB, ds) is None
    assert await repo.get_rows(BOB, ds, 0, 10) == []
    assert await repo.get_datasets(BOB, [ds]) == []


async def test_get_dataset_meta_has_no_rows(repo: Artifacts) -> None:
    ds = await _dataset(repo)
    assert await repo.get_dataset_meta(ALICE, ds) == {
        "id": ds,
        "name": "n",
        "columns": COLUMNS,
        "row_count": 5,
        "truncated": False,
        "source_sql": "SELECT n",
        "created_at": (await repo.get_dataset(ALICE, ds) or {})["created_at"],
    }


async def test_get_datasets_loads_owned_datasets_with_their_rows_in_request_order(repo: Artifacts) -> None:
    first = await _dataset(repo, rows=[[1, "a"]])
    second = await _dataset(repo, rows=[[2, "b"], [3, "c"]])
    empty = await _dataset(repo, rows=[])
    foreign = await _dataset(repo, user=BOB)

    loaded = await repo.get_datasets(ALICE, [second, "ds_missing0000", foreign, empty, first])

    assert [(d["id"], d["rows"]) for d in loaded] == [(second, [[2, "b"], [3, "c"]]), (empty, []), (first, [[1, "a"]])]
