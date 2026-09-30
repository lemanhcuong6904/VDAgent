"""The `user_scopes` table: async reads for the MCP tools, sync seeding for the seed scripts and tests."""

from __future__ import annotations

import sqlite3

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.persistence import fetch_all, tables
from vdagent_contracts.scope import AuthorizedScope, UserContext

# Demo grants (system prompt §7.2): Alice sees PRJ-X, Bob another project.
DEMO_SCOPES: list[tuple[str, str, str | None]] = [
    ("u_000000000001", "PRJ-X", None),
    ("u_000000000002", "PRJ-Y", None),
]

_scopes = tables.user_scopes


class UserScopes:
    """Repository of `user_scopes`."""

    def __init__(self, db: AsyncEngine) -> None:
        self._db = db

    async def user_context(self, user_id: str) -> UserContext:
        """The user's context with its authorized projects and zones (empty for an unknown user)."""
        rows = await fetch_all(
            self._db,
            select(_scopes.c.project_id, _scopes.c.zone_id)
            .where(_scopes.c.user_id == user_id)
            .order_by(_scopes.c.project_id, _scopes.c.zone_id),
        )
        projects = sorted({r["project_id"] for r in rows if r["zone_id"] is None})
        zones = sorted({r["zone_id"] for r in rows if r["zone_id"] is not None})
        return UserContext(user_id=user_id, authorized_scope=AuthorizedScope(project_ids=projects, zone_ids=zones))


def seed_demo_scopes(path: str) -> None:
    """Insert every `DEMO_SCOPES` grant (idempotent; sync, for seed scripts and tests)."""
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT OR IGNORE INTO user_scopes (user_id, project_id, zone_id) VALUES (?, ?, ?)", DEMO_SCOPES)
    conn.close()


def seed_missing_demo_scopes(path: str) -> list[str]:
    """Give each existing demo user its `DEMO_SCOPES` grants only if it has no scope row at all (B-10).

    A user that already has any scope row (a customised or production grant) is left exactly as it is, unknown users get
    nothing, and no global grant exists. Returns the users that were seeded (`[]` on a second run).
    """
    grants: dict[str, list[tuple[str, str | None]]] = {}
    for user_id, project_id, zone_id in DEMO_SCOPES:
        grants.setdefault(user_id, []).append((project_id, zone_id))
    seeded: list[str] = []
    with sqlite3.connect(path) as conn:
        existing_users = {r[0] for r in conn.execute("SELECT id FROM users")}
        scoped = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM user_scopes")}
        for user_id, rows in grants.items():
            if user_id not in existing_users or user_id in scoped:
                continue
            conn.executemany(
                "INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, ?, ?)",
                [(user_id, project, zone) for project, zone in rows],
            )
            seeded.append(user_id)
    conn.close()
    return seeded
