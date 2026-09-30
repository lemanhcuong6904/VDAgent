"""WS2 fixtures: the real Backend MCP tools (backend v2) over a freshly built real-estate DW and a scratch backend.db.

The backend.db is created by the Alembic migrations; every tool call goes through `vdagent_backend.mcp.McpTools` with the
MCP grants of the agent's plugin entry in `backend/config.yaml` — the same checks the MCP server applies.
Nothing here reads the retail warehouse, the Compare hero fixture, the Insight export pack or Chart demo data.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import mcp_types as types
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.config import load_config
from vdagent_backend.core import McpIdentity
from vdagent_backend.mcp import McpTools
from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.re_warehouse import build
from vdagent_backend.scopes import UserScopes, seed_demo_scopes
from vdagent_backend.warehouse import RealEstateWarehouse, Warehouse
from vdagent_data.steps import ToolFailure

ALICE, BOB = "u_000000000001", "u_000000000002"  # Alice: PRJ-X, Bob: PRJ-Y (scopes.DEMO_SCOPES)
NOW = "2026-09-30T00:00:00.000Z"
CONFIG = Path(__file__).resolve().parents[4] / "backend" / "config.yaml"
GRANTS: dict[str, frozenset[str]] = {
    spec.module.removeprefix("vdagent_"): spec.mcp_tools for spec in load_config(CONFIG).plugins if spec.enabled
}


class GrantedTools:
    """TEST ADAPTER (not production): the backend-v2 `McpTools` with the grants of `backend/config.yaml` applied per
    caller agent, keeping the old in-process signature `call(identity, name, args)` of the agent tests.
    Remove once every agent test calls `McpTools.call(identity, granted, name, args)` itself."""

    def __init__(self, db: AsyncEngine, warehouse_db: str, re_db: str, timeout_s: float = 2.0) -> None:
        self.db, self._warehouse_db, self._timeout_s = db, warehouse_db, timeout_s
        self.artifacts = ArtifactService(db)
        self.use_re_warehouse(re_db)

    def use_re_warehouse(self, path: str) -> None:
        """Point the real-estate tools at another DW file (tamper tests)."""
        self.tools = McpTools(self.artifacts, Warehouse(self._warehouse_db, self._timeout_s),
                              re_warehouse=RealEstateWarehouse(path, self._timeout_s), scopes=UserScopes(self.db))

    async def call(self, identity: McpIdentity, name: str, args: dict[str, Any]) -> types.CallToolResult:
        return await self.tools.call(identity, GRANTS.get(identity.agent, frozenset()), name, args)


@pytest.fixture(scope="session")
def re_db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("re") / "re_warehouse.db")
    build(path)
    return path


class McpPort:
    """The `Tools` port of `vdagent_data.steps` over in-process `McpTools` (same code path as the MCP server)."""

    def __init__(self, tools: GrantedTools, identity: McpIdentity) -> None:
        self.tools, self.identity = tools, identity
        self.calls: list[str] = []

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        result = await self.tools.call(self.identity, name, args)
        text = result.content[0].text
        if result.is_error:
            raise ToolFailure(text)
        return json.loads(text)

    def as_agent(self, agent: str) -> McpPort:
        """Same user and task, another agent's MCP identity (its own tool and write permissions)."""
        i = self.identity
        return McpPort(self.tools, McpIdentity(user_id=i.user_id, agent=agent, invocation_id=f"{i.invocation_id}_{agent}", task_id=i.task_id))

    def as_user(self, user: str) -> McpPort:
        return McpPort(self.tools, McpIdentity(user_id=user, agent="data", invocation_id=f"inv_{user}", task_id=f"t_{user}"))


@pytest.fixture
async def mcp_tools(tmp_path: Path, re_db: str) -> AsyncIterator[GrantedTools]:
    path = str(tmp_path / "backend.db")
    await asyncio.to_thread(migrate, sqlite_url(path))  # migrate runs its own event loop
    engine = create_database(sqlite_url(path))
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", [(ALICE, "Alice", NOW), (BOB, "Bob", NOW)])
        for user in (ALICE, BOB):  # datasets reference their creating invocation
            conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, created_at) VALUES (?, ?, 'data', 'running', ?)",
                         (f"t_{user}", user, NOW))
            conn.execute(
                "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                " VALUES (?, ?, ?, 'data', 'orchestrator', 1, 'step', 'running', ?)",
                (f"inv_{user}", f"t_{user}", user, NOW),
            )
            for agent in ("insight", "compare", "chart", "report"):  # McpPort.as_agent identities (reports need them)
                conn.execute(
                    "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                    " VALUES (?, ?, ?, ?, 'orchestrator', 1, 'step', 'running', ?)",
                    (f"inv_{user}_{agent}", f"t_{user}", user, agent, NOW),
                )
    conn.close()
    seed_demo_scopes(path)
    yield GrantedTools(engine, str(tmp_path / "warehouse.db"), re_db)
    await engine.dispose()


@pytest.fixture
def alice(mcp_tools: GrantedTools) -> McpPort:
    return McpPort(mcp_tools, McpIdentity(user_id=ALICE, agent="data", invocation_id=f"inv_{ALICE}", task_id=f"t_{ALICE}"))
