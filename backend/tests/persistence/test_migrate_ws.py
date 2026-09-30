"""Revision 0003 (staging-agent → backend v2): artifact envelopes, user scopes, task outcome and idempotency."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from conftest import ALICE, BOB, NOW
from vdagent_backend.persistence import sqlite_url
from vdagent_backend.persistence.migrate import alembic_config, migrate

STAGING_SCHEMA = Path(__file__).resolve().parents[1] / "fixtures" / "staging_schema.sql"


def _columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return cols


def _artifact(conn: sqlite3.Connection, version: int = 1, status: str = "VALID") -> None:
    conn.execute(
        "INSERT INTO artifacts (artifact_id, version, run_id, task_id, user_id, artifact_type, schema_version, status,"
        " producer_json, content_hash, snapshot_refs_json, semantic_config_version, source_refs_json, input_refs_json,"
        " evidence_refs_json, limitations_json, payload_json, created_at)"
        " VALUES ('art_1', ?, 't_1', 't_1', ?, 'run_state', 'run_state@1', ?, '{}', 'h', '[]', 'sc-1', '[]', '[]', '[]',"
        " '[]', '{}', ?)",
        (version, ALICE, status, NOW),
    )


def test_fresh_database_gets_the_staging_tables_and_columns(tmp_path: Path) -> None:
    path = tmp_path / "b.db"
    migrate(sqlite_url(str(path)))
    assert {"outcome", "idempotency_key"} <= _columns(path, "tasks")
    assert {"artifact_id", "version", "content_hash", "payload_json"} <= _columns(path, "artifacts")
    assert {"user_id", "project_id", "zone_id"} == _columns(path, "user_scopes")
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO users (id, name, created_at) VALUES (?, 'Alice', ?)", (ALICE, NOW))
        _artifact(conn)
        conn.execute("UPDATE artifacts SET status = 'SUPERSEDED' WHERE artifact_id = 'art_1'")  # the only update allowed
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE artifacts SET payload_json = '{\"x\": 1}' WHERE artifact_id = 'art_1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM artifacts")
        conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, created_at, idempotency_key) VALUES ('t_a', ?, 'o', 'running', ?, 'k')", (ALICE, NOW))
        with pytest.raises(sqlite3.IntegrityError):  # one key per (user, agent)
            conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, created_at, idempotency_key) VALUES ('t_b', ?, 'o', 'running', ?, 'k')", (ALICE, NOW))
        conn.execute("INSERT INTO user_scopes (user_id, project_id) VALUES (?, 'PRJ-X')", (ALICE,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO user_scopes (user_id, project_id) VALUES (?, 'PRJ-X')", (ALICE,))
    conn.close()


def test_a_staging_database_is_adopted_and_keeps_its_artifacts_scopes_and_outcomes(tmp_path: Path) -> None:
    path = tmp_path / "staging.db"
    with sqlite3.connect(path) as conn:  # exactly what staging-agent's schema.sql created (no alembic_version)
        conn.executescript(STAGING_SCHEMA.read_text())
        conn.executemany("INSERT INTO users (id, name) VALUES (?, ?)", [(ALICE, "Alice"), (BOB, "Bob")])
        conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, outcome, idempotency_key) VALUES ('t_1', ?, 'orchestrator', 'completed', 'partial', 'k1')", (ALICE,))
        conn.execute("INSERT INTO user_scopes (user_id, project_id) VALUES (?, 'PRJ-X')", (ALICE,))
        _artifact(conn)
    conn.close()
    migrate(sqlite_url(str(path)))
    migrate(sqlite_url(str(path)))  # idempotent
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT outcome, idempotency_key FROM tasks WHERE id = 't_1'").fetchone() == ("partial", "k1")
        assert conn.execute("SELECT project_id FROM user_scopes").fetchall() == [("PRJ-X",)]
        assert conn.execute("SELECT artifact_id, version FROM artifacts").fetchall() == [("art_1", 1)]
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] >= "0003"
    conn.close()


def test_revision_0003_downgrades(tmp_path: Path) -> None:
    path = tmp_path / "b.db"
    url = sqlite_url(str(path))
    migrate(url)
    cfg = alembic_config(url)
    command.downgrade(cfg, "0002")
    assert "outcome" not in _columns(path, "tasks") and _columns(path, "artifacts") == set()
    command.upgrade(cfg, "head")
    assert "outcome" in _columns(path, "tasks")
    with sqlite3.connect(path) as conn:  # the status CHECK survived both directions
        conn.execute("INSERT INTO users (id, name, created_at) VALUES (?, 'Alice', ?)", (ALICE, NOW))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, created_at) VALUES ('t', ?, 'o', 'weird', ?)", (ALICE, NOW))
    conn.close()
