"""B-10: development scopes for the demo users — only for users that have no scope yet, never widened."""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

from vdagent_backend.db import scopes
from vdagent_backend.db.database import apply_schema, create_db

ALICE, BOB = "u_000000000001", "u_000000000002"
REPO = Path(__file__).resolve().parents[2]


def _seed_users_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_users_script", REPO / "data" / "seed_users.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows(path: str) -> list[tuple[str, str, str | None]]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT user_id, project_id, zone_id FROM user_scopes ORDER BY 1, 2, 3").fetchall()
    conn.close()
    return rows


def _fresh(tmp_path: Path) -> str:
    path = str(tmp_path / "backend.db")
    apply_schema(path)
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name) VALUES (?, ?)", [(ALICE, "Alice"), (BOB, "Bob")])
    conn.close()
    return path


def test_first_seed_grants_the_documented_projects(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    assert scopes.seed_missing_demo_scopes(path) == [ALICE, BOB]
    assert _rows(path) == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]


def test_repeated_seed_changes_nothing(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    scopes.seed_missing_demo_scopes(path)
    assert scopes.seed_missing_demo_scopes(path) == []
    assert _rows(path) == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]


def test_existing_custom_scope_is_never_modified(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, 'PRJ-X', 'ZN-A')", (ALICE,))
    conn.close()
    assert scopes.seed_missing_demo_scopes(path) == [BOB]  # Alice already has a scope: left as it is
    assert _rows(path) == [(ALICE, "PRJ-X", "ZN-A"), (BOB, "PRJ-Y", None)]


def test_unknown_users_get_nothing_and_no_global_grant(tmp_path: Path) -> None:
    path = str(tmp_path / "backend.db")
    apply_schema(path)  # no users at all
    assert scopes.seed_missing_demo_scopes(path) == []
    assert _rows(path) == []


def test_alice_cannot_see_prj_y_after_seeding(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    scopes.seed_missing_demo_scopes(path)

    async def contexts() -> tuple[list[str], list[str]]:
        engine = create_db(path)
        try:
            alice = await scopes.get_user_context(engine, ALICE)
            bob = await scopes.get_user_context(engine, BOB)
        finally:
            await engine.dispose()
        return alice.authorized_scope.project_ids, bob.authorized_scope.project_ids

    assert asyncio.run(contexts()) == (["PRJ-X"], ["PRJ-Y"])


def test_seed_users_script_seeds_scopes_on_a_fresh_db_and_is_idempotent(tmp_path: Path, capsys: object) -> None:
    path = str(tmp_path / "backend.db")
    module = _seed_users_module()
    assert module.main(["seed_users.py", path]) == 0
    assert module.main(["seed_users.py", path]) == 0
    assert _rows(path) == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]
