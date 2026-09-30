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


# ---- WS1: the chart agent (docs/integration/AGENT_CONTRACT_MATRIX.md §1, §3.4) ----


def test_chart_is_a_known_agent_with_artifact_tools(tools: McpTools) -> None:
    assert "chart" in ALL_AGENTS
    names = {tool.name for tool in tools.list_for("chart")}
    assert {"artifact_put", "artifact_get", "artifact_list", "get_user_context"} <= names
    assert not names & {"run_query", "re_run_query", "create_chart", "save_report"}


async def test_chart_writes_chart_spec_pinned_to_a_comparison(tools: McpTools) -> None:
    _, cmp = await call(tools, who("compare"), "artifact_put", draft_json=draft("comparison", "compare"))
    err, read = await call(tools, who("chart"), "artifact_get", artifact_id=cmp["artifact_id"])
    assert not err and read["content_hash"] == cmp["content_hash"]
    ref = {"artifact_id": cmp["artifact_id"], "version": 1, "artifact_type": "comparison", "content_hash": cmp["content_hash"]}
    err, spec = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart", input_artifact_refs=[ref]))
    assert not err and spec["artifact_type"] == "chart_spec" and spec["input_artifact_refs"] == [ref]


async def test_chart_cannot_write_other_types_or_read_other_users(tools: McpTools) -> None:
    err, text = await call(tools, who("chart"), "artifact_put", draft_json=draft("insight", "chart"))
    assert err and "cannot write insight" in text
    _, theirs = await call(tools, who("compare", user=BOB), "artifact_put", draft_json=draft("comparison", "compare"))
    err, text = await call(tools, who("chart"), "artifact_get", artifact_id=theirs["artifact_id"])
    assert err and "not found" in text


async def test_artifact_put_reports_broken_input_ref(tools: McpTools) -> None:
    ref = {"artifact_id": "art_missing", "version": 1, "artifact_type": "comparison"}
    err, text = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart", input_artifact_refs=[ref]))
    assert err and "unknown input artifact art_missing@1" in text


async def test_artifact_put_reports_hash_mismatch(tools: McpTools) -> None:
    _, cmp = await call(tools, who("compare"), "artifact_put", draft_json=draft("comparison", "compare"))
    ref = {"artifact_id": cmp["artifact_id"], "version": 1, "artifact_type": "comparison", "content_hash": "0" * 64}
    err, text = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart", input_artifact_refs=[ref]))
    assert err and "content hash" in text


# ---- WS6: save_report embeds chart_spec artifacts (D7) ----------------------------------------------------------------


async def test_save_report_embeds_a_chart_spec_of_this_user(tools: McpTools, tmp_path: Path) -> None:
    import sqlite3

    with sqlite3.connect(tmp_path / "backend.db") as conn:  # reports reference their creating invocation
        conn.execute("INSERT INTO tasks (id, user_id, root_agent, status) VALUES ('t_1', ?, 'report', 'running')", (ALICE,))
        conn.execute("INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status)"
                     " VALUES ('inv_report', 't_1', ?, 'report', 'user', 0, 'r', 'running')", (ALICE,))
    conn.close()
    _, spec = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart"))
    md = f"# R\n\n{{{{chart_spec:{spec['artifact_id']}@1}}}}\n"
    err, saved = await call(tools, who("report"), "save_report", title="R", markdown=md)
    assert not err and saved["report_id"].startswith("rp_")


async def test_save_report_rejects_unknown_foreign_or_non_chart_spec_embeds(tools: McpTools) -> None:
    _, theirs = await call(tools, who("chart", user=BOB), "artifact_put", draft_json=draft("chart_spec", "chart"))
    _, run_state = await call(tools, who("orchestrator"), "artifact_put", draft_json=draft("run_state", "orchestrator"))
    for ref in ("art_missing@1", f"{theirs['artifact_id']}@1", f"{run_state['artifact_id']}@1", "art_x"):
        err, text = await call(tools, who("report"), "save_report", title="R", markdown=f"{{{{chart_spec:{ref}}}}}")
        assert err and "chart_spec" in text, ref
