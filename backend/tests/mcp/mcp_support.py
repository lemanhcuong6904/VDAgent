"""Builds the backend-v2 `McpTools` for in-process tool tests and calls tools with the grants of `backend/config.yaml`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from conftest import ALICE, BOB, NOW, migrated_database, seed_users
from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.config import load_config
from vdagent_backend.core import McpIdentity
from vdagent_backend.mcp import McpTools
from vdagent_backend.scopes import UserScopes, seed_demo_scopes
from vdagent_backend.warehouse import RealEstateWarehouse, Warehouse

CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"
GRANTS: dict[str, frozenset[str]] = {
    spec.module.removeprefix("vdagent_"): spec.mcp_tools for spec in load_config(CONFIG).plugins if spec.enabled
}


def seed_turns(path: str, agents: tuple[str, ...] = ("data", "report"), tasks: tuple[str, ...] = ("t_1",)) -> None:
    """Rows that datasets and reports reference: a task and one invocation per (user, agent)."""
    with sqlite3.connect(path) as conn:
        for user in (ALICE, BOB):
            for task in tasks:
                conn.execute("INSERT OR IGNORE INTO tasks (id, user_id, root_agent, status, created_at) VALUES (?, ?, 'data', 'running', ?)",
                             (f"{task}_{user}" if user == BOB else task, user, NOW))
                for agent in agents:
                    conn.execute(
                        "INSERT OR IGNORE INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                        " VALUES (?, ?, ?, ?, 'user', 0, 'hi', 'running', ?)",
                        (f"inv_{agent}_{user}", f"{task}_{user}" if user == BOB else task, user, agent, NOW),
                    )
    conn.close()


async def build_tools(tmp_path: Path, re_db: str | None = None, timeout_s: float = 1.0) -> tuple[McpTools, Any]:
    path = str(tmp_path / "backend.db")
    db = await migrated_database(path)
    seed_users(path)
    seed_demo_scopes(path)
    seed_turns(path)
    tools = McpTools(
        ArtifactService(db),
        Warehouse(str(tmp_path / "warehouse.db"), timeout_s),
        re_warehouse=RealEstateWarehouse(re_db, timeout_s) if re_db else None,
        scopes=UserScopes(db),
    )
    return tools, db


def who(agent: str, task: str = "t_1", user: str = ALICE) -> McpIdentity:
    return McpIdentity(user_id=user, agent=agent, invocation_id=f"inv_{agent}_{user}", task_id=task)


async def call(tools: McpTools, identity: McpIdentity, name: str, **args: Any) -> tuple[bool, Any]:
    result = await tools.call(identity, GRANTS.get(identity.agent, frozenset()), name, args)
    text = result.content[0].text
    return bool(result.is_error), (text if result.is_error else json.loads(text))
