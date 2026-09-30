"""WS2 fixtures: the real Backend MCP tools over a freshly built real-estate DW and a scratch backend.db.

Nothing here reads the retail warehouse, the Compare hero fixture, the Insight export pack or Chart demo data.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.db import scopes
from vdagent_backend.db.database import create_db
from vdagent_backend.mcp.tools import McpTools
from vdagent_backend.re_warehouse import build
from vdagent_backend.tokens import McpIdentity
from vdagent_data.steps import ToolFailure

ALICE, BOB = "u_000000000001", "u_000000000002"  # Alice: PRJ-X, Bob: PRJ-Y (scopes.DEMO_SCOPES)


@pytest.fixture(scope="session")
def re_db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("re") / "re_warehouse.db")
    build(path)
    return path


class McpPort:
    """The `Tools` port of `vdagent_data.steps` over in-process `McpTools` (same code path as the MCP server)."""

    def __init__(self, tools: McpTools, identity: McpIdentity) -> None:
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
async def mcp_tools(tmp_path: Path, re_db: str) -> AsyncIterator[McpTools]:
    path = str(tmp_path / "backend.db")
    engine = create_db(path)
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name) VALUES (?, ?)", [(ALICE, "Alice"), (BOB, "Bob")])
        for user in (ALICE, BOB):  # datasets reference their creating invocation
            conn.execute("INSERT INTO tasks (id, user_id, root_agent, status) VALUES (?, ?, 'data', 'running')", (f"t_{user}", user))
            conn.execute(
                "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status)"
                " VALUES (?, ?, ?, 'data', 'orchestrator', 1, 'step', 'running')",
                (f"inv_{user}", f"t_{user}", user),
            )
            for agent in ("insight", "compare", "chart", "report"):  # McpPort.as_agent identities (reports need them)
                conn.execute(
                    "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status)"
                    " VALUES (?, ?, ?, ?, 'orchestrator', 1, 'step', 'running')",
                    (f"inv_{user}_{agent}", f"t_{user}", user, agent),
                )
    conn.close()
    scopes.seed_demo_scopes(path)
    yield McpTools(engine, str(tmp_path / "warehouse.db"), re_warehouse_db=re_db, sql_timeout_s=2.0)
    await engine.dispose()


@pytest.fixture
def alice(mcp_tools: McpTools) -> McpPort:
    return McpPort(mcp_tools, McpIdentity(user_id=ALICE, agent="data", invocation_id=f"inv_{ALICE}", task_id=f"t_{ALICE}"))
