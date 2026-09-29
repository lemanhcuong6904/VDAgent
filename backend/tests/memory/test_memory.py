"""Agent memory (agent-freedom spec §2): notes scoped to (user, agent), keyword and vector search."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from conftest import ALICE, BOB, seed_users
from vdagent_backend.db.database import create_db
from vdagent_backend.db.memory import ScopedMemory


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[object]:
    path = str(tmp_path / "backend.db")
    engine = create_db(path)
    seed_users(path)
    yield engine
    await engine.dispose()


def mem(db: object, user: str = ALICE, agent: str = "insight") -> ScopedMemory:
    return ScopedMemory(db, user, agent)  # type: ignore[arg-type]


async def test_notes_are_invisible_outside_their_user_and_agent_scope(db: object) -> None:
    mine = mem(db)
    note_id = await mine.save("West revenue fell 8% in 2025", "finding", [1.0, 0.0])
    for other in (mem(db, user=BOB), mem(db, agent="report")):
        assert await other.search("revenue") == []
        assert await other.search("revenue", embedding=[1.0, 0.0]) == []
        assert await other.recent() == []
        assert await other.delete(note_id) is False
    assert [n.id for n in await mine.recent()] == [note_id]


async def test_keyword_search_matches_and_ranks_best_first(db: object) -> None:
    m = mem(db)
    await m.save("East region grew 12 percent", "finding")
    best = await m.save("West revenue fell; West region stores closed", "finding")
    await m.save("Electronics revenue rose", "finding")

    notes = await m.search("west region", limit=5)

    assert notes[0].id == best
    assert {n.text for n in notes} == {"West revenue fell; West region stores closed", "East region grew 12 percent"}
    assert all(n.score is not None for n in notes)


@pytest.mark.parametrize("query", ['revenue" OR (', "NEAR(west*", "-west AND", "what's up?"])
async def test_keyword_search_never_raises_on_fts_syntax_or_punctuation(db: object, query: str) -> None:
    m = mem(db)
    await m.save("west revenue", "finding")
    await m.search(query)


async def test_keyword_search_without_words_returns_nothing(db: object) -> None:
    m = mem(db)
    await m.save("west revenue", "finding")
    assert await m.search("  ?! ") == []


async def test_vector_search_returns_nearest_first_and_skips_other_dimensions_and_unembedded(db: object) -> None:
    m = mem(db)
    far = await m.save("far", "finding", [0.0, 1.0])
    near = await m.save("near", "finding", [1.0, 0.1])
    await m.save("three dims", "finding", [1.0, 0.0, 0.0])
    await m.save("no vector", "finding")

    notes = await m.search("ignored", limit=5, embedding=[1.0, 0.0])

    assert [n.id for n in notes] == [near, far]
    assert notes[0].score is not None and notes[0].score < notes[1].score  # type: ignore[operator]


async def test_recent_is_newest_first_and_limited(db: object) -> None:
    m = mem(db)
    ids = [await m.save(f"note {i}") for i in range(3)]
    notes = await m.recent(limit=2)
    assert [n.id for n in notes] == [ids[2], ids[1]]
    assert (notes[0].kind, notes[0].text) == ("note", "note 2")


async def test_delete_removes_the_note_from_recent_and_search(db: object) -> None:
    m = mem(db)
    note_id = await m.save("west revenue", "finding", [1.0, 0.0])
    assert await m.delete(note_id) is True
    assert await m.recent() == []
    assert await m.search("west") == []
    assert await m.search("west", embedding=[1.0, 0.0]) == []
    assert await m.delete(note_id) is False


@pytest.mark.parametrize(("text", "kind", "embedding"), [("", "note", None), ("  ", "note", None), ("x", "", None), ("x", "note", [])])
async def test_save_rejects_empty_text_kind_or_embedding(db: object, text: str, kind: str, embedding: list[float] | None) -> None:
    with pytest.raises(ValueError):
        await mem(db).save(text, kind, embedding)
