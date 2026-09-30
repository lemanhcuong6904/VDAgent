"""User scopes (D8, B-10): the Backend is the only source of a user's authorized scope; demo grants are seeded only
for demo users that have none, never widened."""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

from conftest import ALICE, BOB, NOW
from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.scopes import DEMO_SCOPES, UserScopes, seed_demo_scopes, seed_missing_demo_scopes
from vdagent_contracts.scope import UserContext

REPO = Path(__file__).resolve().parents[3]


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


def _fresh(tmp_path: Path, users: bool = True) -> str:
    path = str(tmp_path / "backend.db")
    migrate(sqlite_url(path))
    if users:
        with sqlite3.connect(path) as conn:
            conn.executemany("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", [(ALICE, "Alice", NOW), (BOB, "Bob", NOW)])
        conn.close()
    return path


def _contexts(path: str, *users: str) -> list[UserContext]:
    async def run() -> list[UserContext]:
        db = create_database(sqlite_url(path))
        try:
            return [await UserScopes(db).user_context(u) for u in users]
        finally:
            await db.dispose()

    return asyncio.run(run())


def test_demo_scopes_are_the_documented_grants() -> None:
    assert DEMO_SCOPES == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]


def test_first_seed_grants_the_documented_projects(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    assert seed_missing_demo_scopes(path) == [ALICE, BOB]
    assert _rows(path) == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]


def test_repeated_seed_changes_nothing(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    seed_missing_demo_scopes(path)
    assert seed_missing_demo_scopes(path) == []
    seed_demo_scopes(path)  # the unconditional seed is idempotent too
    assert _rows(path) == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]


def test_existing_custom_scope_is_never_modified(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, 'PRJ-X', 'ZN-A')", (ALICE,))
    conn.close()
    assert seed_missing_demo_scopes(path) == [BOB]
    assert _rows(path) == [(ALICE, "PRJ-X", "ZN-A"), (BOB, "PRJ-Y", None)]


def test_unknown_users_get_nothing_and_no_global_grant(tmp_path: Path) -> None:
    path = _fresh(tmp_path, users=False)
    assert seed_missing_demo_scopes(path) == []
    assert _rows(path) == []


def test_user_context_is_per_user_and_unknown_users_have_an_empty_scope(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    seed_missing_demo_scopes(path)
    alice, bob, nobody = _contexts(path, ALICE, BOB, "u_unknown")
    assert (alice.authorized_scope.project_ids, bob.authorized_scope.project_ids) == (["PRJ-X"], ["PRJ-Y"])
    assert alice.authorized_scope.zone_ids == [] and alice.user_id == ALICE
    assert nobody == UserContext(user_id="u_unknown")


def test_zone_grants_are_zones_not_projects(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, 'PRJ-X', 'ZN-A')", (ALICE,))
    conn.close()
    [alice] = _contexts(path, ALICE)
    assert (alice.authorized_scope.project_ids, alice.authorized_scope.zone_ids) == ([], ["ZN-A"])


def test_seed_users_script_migrates_seeds_scopes_and_is_idempotent(tmp_path: Path) -> None:
    path = str(tmp_path / "backend.db")
    module = _seed_users_module()
    assert module.main(["seed_users.py", path]) == 0
    assert module.main(["seed_users.py", path]) == 0
    assert _rows(path) == [(ALICE, "PRJ-X", None), (BOB, "PRJ-Y", None)]
