"""user_scopes + MCP get_user_context (D8): the Backend issues the user context, never the question or an LLM."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from conftest import ALICE, BOB, seed_users
from vdagent_backend.db import scopes
from vdagent_backend.db.database import create_db
from vdagent_backend.mcp.tools import ALL_AGENTS, PERMISSIONS, McpTools
from vdagent_backend.tokens import McpIdentity
from vdagent_contracts.scope import UserContext


@pytest.fixture
async def tools(tmp_path: Path) -> AsyncIterator[McpTools]:
    path = str(tmp_path / "backend.db")
    engine = create_db(path)
    seed_users(path)
    scopes.seed_demo_scopes(path)
    yield McpTools(engine, str(tmp_path / "warehouse.db"), sql_timeout_s=1.0)
    await engine.dispose()


async def context_of(tools: McpTools, user: str, **args: Any) -> tuple[bool, Any]:
    identity = McpIdentity(user_id=user, agent="data", invocation_id="inv_1", task_id="t_1")
    result = await tools.call(identity, "get_user_context", args)
    text = result.content[0].text
    return result.is_error, (text if result.is_error else json.loads(text))


async def test_alice_sees_only_prj_x(tools: McpTools) -> None:
    err, ctx = await context_of(tools, ALICE)
    assert not err
    parsed = UserContext.model_validate(ctx)
    assert parsed.user_id == ALICE
    assert parsed.authorized_scope.project_ids == ["PRJ-X"]
    assert parsed.authorized_scope.zone_ids == []


async def test_bob_sees_other_project(tools: McpTools) -> None:
    _, ctx = await context_of(tools, BOB)
    assert ctx["authorized_scope"]["project_ids"] == ["PRJ-Y"]


async def test_get_user_context_never_other_user(tools: McpTools) -> None:
    _, alice = await context_of(tools, ALICE)
    _, bob = await context_of(tools, BOB)
    assert "PRJ-Y" not in alice["authorized_scope"]["project_ids"]
    assert "PRJ-X" not in bob["authorized_scope"]["project_ids"]


async def test_user_context_not_accepted_from_arguments(tools: McpTools) -> None:
    err, text = await context_of(tools, ALICE, user_id=BOB)
    assert err and "no arguments" in text
    assert PERMISSIONS["get_user_context"] == ALL_AGENTS


async def test_unknown_user_empty_scope(tmp_path: Path) -> None:
    path = str(tmp_path / "b.db")
    engine = create_db(path)
    try:
        ctx = await scopes.get_user_context(engine, "u_unknown")
        assert ctx == UserContext(user_id="u_unknown")
    finally:
        await engine.dispose()
