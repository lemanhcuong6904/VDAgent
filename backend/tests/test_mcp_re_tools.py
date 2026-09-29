"""re_* MCP tools over the real-estate DW mock (system prompt §6.3): Data only, SELECT only, scoped by the Backend."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from conftest import ALICE, BOB, seed_users
from vdagent_backend.db import scopes
from vdagent_backend.db.database import create_db
from vdagent_backend.mcp.tools import PERMISSIONS, McpTools
from vdagent_backend.re_warehouse import build
from vdagent_backend.tokens import McpIdentity

CANDIDATES = (
    "SELECT m.unit_code, m.project_key FROM dim_unit_master m"
    " WHERE m.launch_batch_id IN ('LB-01','LB-02','LB-03') AND m.unit_code <> 'A12-08'"
)


@pytest.fixture(scope="module")
def re_db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("re") / "re.db")
    build(path)
    return path


@pytest.fixture
async def tools(tmp_path: Path, re_db: str) -> AsyncIterator[McpTools]:
    path = str(tmp_path / "backend.db")
    engine = create_db(path)
    seed_users(path)
    scopes.seed_demo_scopes(path)
    with sqlite3.connect(path) as conn:  # datasets reference their creating invocation
        for user in (ALICE, BOB):
            conn.execute("INSERT INTO tasks (id, user_id, root_agent, status) VALUES (?, ?, 'data', 'running')", (f"t_{user}", user))
            conn.execute(
                "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status)"
                " VALUES (?, ?, ?, 'data', 'user', 0, 'hi', 'running')",
                (f"inv_{user}", f"t_{user}", user),
            )
    conn.close()
    yield McpTools(engine, str(tmp_path / "warehouse.db"), re_warehouse_db=re_db, sql_timeout_s=0.5)
    await engine.dispose()


async def call(tools: McpTools, name: str, user: str = ALICE, agent: str = "data", **args: Any) -> tuple[bool, Any]:
    identity = McpIdentity(user_id=user, agent=agent, invocation_id=f"inv_{user}", task_id=f"t_{user}")
    result = await tools.call(identity, name, args)
    text = result.content[0].text
    return result.is_error, (text if result.is_error else json.loads(text))


def test_re_tools_only_for_data() -> None:
    for tool in ("re_list_tables", "re_describe_table", "re_run_query"):
        assert PERMISSIONS[tool] == frozenset({"data"})


async def test_re_run_query_rejects_non_select(tools: McpTools) -> None:
    for sql in ("DELETE FROM dim_unit_master", "SELECT 1; DROP TABLE dim_unit_master", "PRAGMA table_info(x)"):
        err, text = await call(tools, "re_run_query", sql=sql)
        assert err, sql
    err, _ = await call(tools, "re_run_query", agent="insight", sql="SELECT 1")
    assert err


async def test_re_run_query_blocks_out_of_scope_project(tools: McpTools) -> None:
    err, result = await call(tools, "re_run_query", sql=CANDIDATES, count_hidden=True)
    assert not err
    assert {r[1] for r in result["preview"]} == {"PRJ-X"}
    assert result["row_count"] == 12 and result["hidden_rows"] == 1  # D12-09 of PRJ-Y
    assert result["dataset_id"].startswith("ds_")
    _, bob = await call(tools, "re_run_query", user=BOB, sql=CANDIDATES)
    assert {r[1] for r in bob["preview"]} == {"PRJ-Y"}
    _, joined = await call(
        tools, "re_run_query",
        sql="SELECT COUNT(*) FROM unit_diagnostic_causes c JOIN dim_unit_master m USING (unit_key) WHERE m.project_key <> 'PRJ-X'",
    )
    assert joined["preview"] == [[0]]
    err, text = await call(tools, "re_run_query", sql="SELECT * FROM main.dim_unit_master")
    assert err and "prohibited" in text


async def test_re_run_query_row_cap_and_timeout(tools: McpTools) -> None:
    err, text = await call(
        tools, "re_run_query", sql="WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    )
    assert err and "time limit" in text


async def test_re_list_and_describe_use_scoped_rows(tools: McpTools) -> None:
    _, tables = await call(tools, "re_list_tables")
    names = {t["name"] for t in tables["tables"]}
    assert "fact_unit_inventory_snapshot" in names and "semantic_config" in names
    _, described = await call(tools, "re_describe_table", table="dim_project_profile", sample_rows=10)
    assert [r[0] for r in described["sample_rows"]] == ["PRJ-X"]
    err, _ = await call(tools, "re_describe_table", table="nope")
    assert err
