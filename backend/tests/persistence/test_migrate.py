"""Alembic migrations: fresh databases, adoption of pre-Alembic databases, and drift."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from conftest import ALICE, LEGACY_DATASET, LEGACY_TASK, build_legacy_db
from vdagent_backend.persistence import sqlite_url
from vdagent_backend.persistence.migrate import alembic_config, include_name, migrate
from vdagent_backend.persistence.tables import metadata


def _head(url: str) -> str:
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    assert head is not None
    return head


def _version(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    conn.close()
    return version


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    return names


def test_a_fresh_database_migrates_to_head_and_a_rerun_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "backend.db"
    url = sqlite_url(str(path))
    migrate(url)
    migrate(url)
    assert _version(path) == _head(url)
    assert set(metadata.tables) | {"memories_fts", "alembic_version"} <= _tables(path)


def test_a_migrated_database_matches_the_table_metadata(tmp_path: Path) -> None:
    path = tmp_path / "backend.db"
    migrate(sqlite_url(str(path)))
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"include_name": include_name})
        assert compare_metadata(context, metadata) == []
    engine.dispose()


def test_a_pre_alembic_database_is_adopted_in_place_keeping_its_data(tmp_path: Path) -> None:
    path = tmp_path / "backend.db"
    build_legacy_db(str(path))
    url = sqlite_url(str(path))
    migrate(url)
    assert _version(path) == _head(url)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM tasks WHERE id = ?", (LEGACY_TASK,)).fetchone() == ("completed",)
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (ALICE,)).fetchone() == (4,)
        match = "SELECT m.text FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid WHERE memories_fts MATCH 'west'"
        assert conn.execute(match).fetchall() == [("west revenue fell",)]
    conn.close()


def test_dataset_rows_move_out_of_rows_json_in_order(tmp_path: Path) -> None:
    path = tmp_path / "backend.db"
    build_legacy_db(str(path))
    rows = [["b", 2, None], ["a", 1.5, "x"], ["c", 3, "y"]]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO datasets (id, user_id, invocation_id, source_sql, columns_json, rows_json, row_count)"
            " VALUES ('ds_three000001', ?, 'inv_legacy0001', 'SELECT 1', '[]', ?, 3)",
            (ALICE, json.dumps(rows)),
        )
    conn.close()

    migrate(sqlite_url(str(path)))

    with sqlite3.connect(path) as conn:
        moved = conn.execute("SELECT idx, row FROM dataset_rows WHERE dataset_id = 'ds_three000001' ORDER BY idx")
        assert [(idx, json.loads(row)) for idx, row in moved] == list(enumerate(rows))
        legacy = conn.execute("SELECT row FROM dataset_rows WHERE dataset_id = ? ORDER BY idx", (LEGACY_DATASET,))
        assert [json.loads(r) for (r,) in legacy] == [[0], [1], [2]]
        assert "rows_json" not in {c[1] for c in conn.execute("PRAGMA table_info(datasets)")}
    conn.close()
