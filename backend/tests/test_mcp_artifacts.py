"""MCP artifact tools (D5, system prompt §6.3, DEC-024): typed writes per agent, user-scoped reads."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from conftest import ALICE, BOB, seed_users
from vdagent_backend.db.database import create_db
from vdagent_backend.mcp.tools import ALL_AGENTS, PERMISSIONS, WRITABLE_TYPES, McpTools
from vdagent_backend.tokens import McpIdentity, TokenRegistry


@pytest.fixture
async def tools(tmp_path: Path) -> AsyncIterator[McpTools]:
    path = str(tmp_path / "backend.db")
    engine = create_db(path)
    seed_users(path)
    yield McpTools(engine, str(tmp_path / "warehouse.db"), sql_timeout_s=1.0)
    await engine.dispose()


def who(agent: str, task: str = "t_1", user: str = ALICE) -> McpIdentity:
    return McpIdentity(user_id=user, agent=agent, invocation_id=f"inv_{agent}", task_id=task)


def draft(artifact_type: str, agent: str, **extra: Any) -> str:
    body = {
        "artifact_type": artifact_type,
        "schema_version": f"{artifact_type}@1",
        "status": "VALID",
        "producer": {"agent": agent, "agent_version": "0.1.0"},
        "payload": {"ratio": 0.68, "n": 7},  # a JSON float: parsed as Decimal, never as float
        **extra,
    }
    return json.dumps(body)


async def call(tools: McpTools, identity: McpIdentity, name: str, **args: Any) -> tuple[bool, Any]:
    result = await tools.call(identity, name, args)
    text = result.content[0].text
    return result.is_error, (text if result.is_error else json.loads(text))


def test_mcp_identity_carries_task_id() -> None:
    registry = TokenRegistry()
    token = registry.issue(ALICE, "data", "inv_1", "t_42")
    identity = registry.resolve(token)
    assert identity is not None and identity.task_id == "t_42"


async def test_artifact_put_only_own_type(tools: McpTools) -> None:
    err, stored = await call(tools, who("data"), "artifact_put", draft_json=draft("data_package", "data"))
    assert not err
    assert stored["run_id"] == "t_1" and stored["task_id"] == "t_1" and stored["version"] == 1
    assert stored["payload"]["ratio"] == "0.68"
    err, text = await call(tools, who("data"), "artifact_put", draft_json=draft("insight", "data"))
    assert err and "cannot write" in text
    err, text = await call(tools, who("data"), "artifact_put", draft_json="{not json")
    assert err and text.startswith("error:")


async def test_artifact_get_other_user_is_unknown(tools: McpTools) -> None:
    _, stored = await call(tools, who("data"), "artifact_put", draft_json=draft("data_package", "data"))
    err, text = await call(tools, who("insight", user=BOB), "artifact_get", artifact_id=stored["artifact_id"])
    assert err and "not found" in text
    err, got = await call(tools, who("insight"), "artifact_get", artifact_id=stored["artifact_id"], version=1)
    assert not err and got["content_hash"] == stored["content_hash"]


async def test_artifact_list_run_filter(tools: McpTools) -> None:
    await call(tools, who("data", task="t_1"), "artifact_put", draft_json=draft("data_package", "data"))
    await call(tools, who("data", task="t_2"), "artifact_put", draft_json=draft("data_package", "data"))
    _, listed = await call(tools, who("insight", task="t_2"), "artifact_list", run_id="t_1")
    assert [a["run_id"] for a in listed["artifacts"]] == ["t_1"]
    _, everything = await call(tools, who("insight", task="t_2"), "artifact_list")
    assert len(everything["artifacts"]) == 2
    assert all("payload" not in a for a in everything["artifacts"])  # listing is a summary; get returns payloads


async def test_orchestrator_reads_run_state_of_previous_task_same_user(tools: McpTools) -> None:
    _, saved = await call(tools, who("orchestrator", task="t_1"), "artifact_put", draft_json=draft("run_state", "orchestrator"))
    # the user's answer arrives as a new task; the orchestrator resumes run t_1 from it
    _, listed = await call(tools, who("orchestrator", task="t_2"), "artifact_list", run_id="t_1", artifact_type="run_state")
    assert [a["artifact_id"] for a in listed["artifacts"]] == [saved["artifact_id"]]
    err, again = await call(
        tools, who("orchestrator", task="t_2"), "artifact_put",
        draft_json=draft("run_state", "orchestrator", artifact_id=saved["artifact_id"]), run_id="t_1",
    )
    assert not err and again["run_id"] == "t_1" and again["task_id"] == "t_2" and again["version"] == 2
    err, text = await call(tools, who("data", task="t_2"), "artifact_put", draft_json=draft("data_package", "data"), run_id="t_zz")
    assert err and "run" in text  # only the current task or a run this user already has


def test_permissions_table_matches_sp_6_3() -> None:
    for tool in ("artifact_put", "artifact_get", "artifact_list"):
        assert PERMISSIONS[tool] == ALL_AGENTS
    assert WRITABLE_TYPES == {
        "orchestrator": {"run_summary", "run_state"},
        "data": {"data_package", "metric", "dq", "dataset"},
        "compare": {"peer_definition", "comparison", "market_context"},
        "insight": {"insight"},
        "chart": {"chart_spec"},
        "report": {"report"},
    }
