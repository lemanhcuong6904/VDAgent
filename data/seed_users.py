"""Migrate the backend database and insert the demo users (idempotent).

Usage: uv run python data/seed_users.py [PATH]
PATH defaults to `backend_db` from the backend config (`VDAGENT_BACKEND_DB` / `VDAGENT_CONFIG` honoured).
"""

from __future__ import annotations

import asyncio
import sys

from vdagent_backend.config import load_config
from vdagent_backend.conversations import Users
from vdagent_backend.persistence import create_database, migrate, sqlite_url

DEMO_USERS = [("u_000000000001", "Alice"), ("u_000000000002", "Bob")]


async def _ensure_users(url: str) -> int:
    db = create_database(url)
    try:
        return await Users(db).ensure(DEMO_USERS)
    finally:
        await db.dispose()


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else load_config().backend_db
    url = sqlite_url(path)
    migrate(url)
    total = asyncio.run(_ensure_users(url))
    print(f"backend db: {path}  demo users ensured: {', '.join(n for _, n in DEMO_USERS)}  users total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
