"""Authorized scope per user (D8): the only source of `user_context` for every agent.

A row grants a whole project (`zone_id` NULL) or one zone of it. An unknown user has an empty scope.
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_contracts.scope import AuthorizedScope, UserContext

# Demo grants (system prompt §7.2): Alice sees PRJ-X, Bob another project.
DEMO_SCOPES: list[tuple[str, str, str | None]] = [
    ("u_000000000001", "PRJ-X", None),
    ("u_000000000002", "PRJ-Y", None),
]


async def get_user_context(db: AsyncEngine, user_id: str) -> UserContext:
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT project_id, zone_id FROM user_scopes WHERE user_id = :u ORDER BY project_id, zone_id"),
                {"u": user_id},
            )
        ).all()
    projects = sorted({r.project_id for r in rows if r.zone_id is None})
    zones = sorted({r.zone_id for r in rows if r.zone_id is not None})
    return UserContext(user_id=user_id, authorized_scope=AuthorizedScope(project_ids=projects, zone_ids=zones))


def seed_demo_scopes(path: str) -> None:
    """Insert DEMO_SCOPES (idempotent; sync, for seed scripts and tests)."""
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO user_scopes (user_id, project_id, zone_id) VALUES (?, ?, ?)", DEMO_SCOPES
        )
    conn.close()


def seed_missing_demo_scopes(path: str) -> list[str]:
    """Development seed (B-10): give each existing demo user its DEMO_SCOPES grants only if it has no scope at all.

    A user that already has any scope row (a customised or production grant) is left exactly as it is, unknown users
    get nothing, and no global grant exists. Returns the users that were seeded (idempotent: `[]` on a second run).
    """
    grants: dict[str, list[tuple[str, str | None]]] = {}
    for user_id, project_id, zone_id in DEMO_SCOPES:
        grants.setdefault(user_id, []).append((project_id, zone_id))
    seeded: list[str] = []
    with sqlite3.connect(path) as conn:
        for user_id, rows in grants.items():
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                continue
            if conn.execute("SELECT 1 FROM user_scopes WHERE user_id = ? LIMIT 1", (user_id,)).fetchone() is not None:
                continue
            conn.executemany(
                "INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, ?, ?)",
                [(user_id, project_id, zone_id) for project_id, zone_id in rows],
            )
            seeded.append(user_id)
    conn.close()
    return seeded
