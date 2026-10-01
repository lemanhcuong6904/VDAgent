"""MCP tools of the six-agent DAG on backend v2 (WS1–WS7): artifact envelopes, user context, real-estate DW."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from conftest import ALICE, BOB
from mcp_support import GRANTS, build_tools, call, who
from vdagent_backend.mcp import TOOLS, WRITABLE_TYPES, McpTools
from vdagent_backend.re_warehouse import build
from vdagent_contracts.scope import UserContext

CANDIDATES = (
    "SELECT m.unit_code, m.project_key FROM dim_unit_master m"
    " WHERE m.launch_batch_id IN ('LB-01','LB-02','LB-03') AND m.unit_code <> 'A12-08'"
)
EVERYONE = {"describe_dataset", "get_dataset_rows", "artifact_put", "artifact_get", "artifact_list", "get_user_context"}
# The WS1–WS7 permission matrix, stated independently of the configuration.
EXPECTED_GRANTS = {
    "orchestrator": EVERYONE,
    "data": EVERYONE | {"list_tables", "describe_table", "run_query", "query_datasets", "re_list_tables", "re_describe_table", "re_run_query"},
    "compare": EVERYONE | {"query_datasets"},
    "insight": EVERYONE | {"query_datasets"},
    "report": EVERYONE | {"create_chart", "save_report"},
    "chart": EVERYONE,
}


@pytest.fixture(scope="module")
def re_db(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("re") / "re.db")
    build(path)
    return path


@pytest.fixture
async def tools(tmp_path: Path, re_db: str) -> AsyncIterator[McpTools]:
    built, db = await build_tools(tmp_path, re_db, timeout_s=0.5)
    yield built
    await db.dispose()


def draft(artifact_type: str, agent: str, **extra: Any) -> str:
    body = {"artifact_type": artifact_type, "schema_version": f"{artifact_type}@1", "status": "VALID",
            "producer": {"agent": agent, "agent_version": "0.1.0"},
            "payload": {"ratio": 0.68, "n": 7}, **extra}  # a JSON float: parsed as Decimal, never as float
    return json.dumps(body)


# ---- grants -----------------------------------------------------------------------------------------------------------


def test_configured_grants_are_the_permission_matrix() -> None:
    assert {agent: set(tools) for agent, tools in GRANTS.items()} == EXPECTED_GRANTS
    assert {t.name for t in TOOLS} >= set().union(*EXPECTED_GRANTS.values())


def test_writable_types_per_agent() -> None:
    assert WRITABLE_TYPES == {
        "orchestrator": {"run_summary", "run_state"},
        "data": {"data_package", "metric", "dq", "dataset"},
        "compare": {"peer_definition", "comparison", "market_context"},
        "insight": {"insight"},
        "chart": {"chart_spec"},
        "report": {"report"},
    }


def test_count_hidden_is_not_offered() -> None:  # WS7 F-08
    assert "count_hidden" not in json.dumps([t.input_schema for t in TOOLS])


# ---- artifact envelopes -----------------------------------------------------------------------------------------------


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
    assert all("payload" not in a for a in everything["artifacts"])


async def test_orchestrator_reads_run_state_of_previous_task_same_user(tools: McpTools) -> None:
    _, saved = await call(tools, who("orchestrator", task="t_1"), "artifact_put", draft_json=draft("run_state", "orchestrator"))
    _, listed = await call(tools, who("orchestrator", task="t_2"), "artifact_list", run_id="t_1", artifact_type="run_state")
    assert [a["artifact_id"] for a in listed["artifacts"]] == [saved["artifact_id"]]
    err, again = await call(tools, who("orchestrator", task="t_2"), "artifact_put",
                            draft_json=draft("run_state", "orchestrator", artifact_id=saved["artifact_id"]), run_id="t_1")
    assert not err and again["run_id"] == "t_1" and again["task_id"] == "t_2" and again["version"] == 2
    err, text = await call(tools, who("data", task="t_2"), "artifact_put", draft_json=draft("data_package", "data"), run_id="t_zz")
    assert err and "run" in text


async def test_chart_writes_chart_spec_pinned_to_a_comparison(tools: McpTools) -> None:
    _, cmp = await call(tools, who("compare"), "artifact_put", draft_json=draft("comparison", "compare"))
    ref = {"artifact_id": cmp["artifact_id"], "version": 1, "artifact_type": "comparison", "content_hash": cmp["content_hash"]}
    err, spec = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart", input_artifact_refs=[ref]))
    assert not err and spec["artifact_type"] == "chart_spec" and spec["input_artifact_refs"] == [ref]
    err, text = await call(tools, who("chart"), "artifact_put", draft_json=draft("insight", "chart"))
    assert err and "cannot write insight" in text
    err, text = await call(tools, who("chart"), "run_query", sql="SELECT 1")
    assert err and "not available" in text


async def test_artifact_put_reports_broken_ref_and_hash_mismatch(tools: McpTools) -> None:
    missing = {"artifact_id": "art_missing", "version": 1, "artifact_type": "comparison"}
    err, text = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart", input_artifact_refs=[missing]))
    assert err and "unknown input artifact art_missing@1" in text
    _, cmp = await call(tools, who("compare"), "artifact_put", draft_json=draft("comparison", "compare"))
    bad = {"artifact_id": cmp["artifact_id"], "version": 1, "artifact_type": "comparison", "content_hash": "0" * 64}
    err, text = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart", input_artifact_refs=[bad]))
    assert err and "content hash" in text


async def test_save_report_embeds_only_this_users_chart_specs(tools: McpTools) -> None:
    _, spec = await call(tools, who("chart"), "artifact_put", draft_json=draft("chart_spec", "chart"))
    err, saved = await call(tools, who("report"), "save_report", title="R", markdown=f"# R\n\n{{{{chart_spec:{spec['artifact_id']}@1}}}}\n")
    assert not err and saved["report_id"].startswith("rp_")
    _, theirs = await call(tools, who("chart", user=BOB), "artifact_put", draft_json=draft("chart_spec", "chart"))
    _, run_state = await call(tools, who("orchestrator"), "artifact_put", draft_json=draft("run_state", "orchestrator"))
    for ref in ("art_missing@1", f"{theirs['artifact_id']}@1", f"{run_state['artifact_id']}@1", "art_x"):
        err, text = await call(tools, who("report"), "save_report", title="R", markdown=f"{{{{chart_spec:{ref}}}}}")
        assert err and "chart_spec" in text, ref


# ---- user context -----------------------------------------------------------------------------------------------------


async def test_user_context_comes_from_the_backend_only(tools: McpTools) -> None:
    err, ctx = await call(tools, who("data"), "get_user_context")
    assert not err
    parsed = UserContext.model_validate(ctx)
    assert (parsed.user_id, parsed.authorized_scope.project_ids, parsed.authorized_scope.zone_ids) == (ALICE, ["PRJ-X"], [])
    _, bob = await call(tools, who("data", user=BOB), "get_user_context")
    assert bob["authorized_scope"]["project_ids"] == ["PRJ-Y"]
    err, text = await call(tools, who("data"), "get_user_context", user_id=BOB)
    assert err and "no arguments" in text


# ---- real-estate DW (scoped; Data only) -------------------------------------------------------------------------------


async def test_re_run_query_says_which_warehouse_answered(tools: McpTools, re_db: str) -> None:
    err, result = await call(tools, who("data"), "re_run_query", sql=CANDIDATES)
    assert not err and result["warehouse"] == {"backend": "sqlite", "file": Path(re_db).name}


async def test_re_run_query_rejects_non_select_and_other_agents(tools: McpTools) -> None:
    for sql in ("DELETE FROM dim_unit_master", "SELECT 1; DROP TABLE dim_unit_master", "PRAGMA table_info(x)"):
        err, _ = await call(tools, who("data"), "re_run_query", sql=sql)
        assert err, sql
    err, text = await call(tools, who("insight"), "re_run_query", sql="SELECT 1")
    assert err and "not available" in text


async def test_re_run_query_blocks_out_of_scope_rows_and_never_counts_them(tools: McpTools) -> None:
    err, result = await call(tools, who("data"), "re_run_query", sql=CANDIDATES)
    assert not err
    assert {r[1] for r in result["preview"]} == {"PRJ-X"}
    assert result["row_count"] == 12 and "hidden_rows" not in result  # WS7 F-08
    assert result["dataset_id"].startswith("ds_")
    err, _ = await call(tools, who("data"), "re_run_query", sql=CANDIDATES, count_hidden=True)
    assert err
    _, bob = await call(tools, who("data", user=BOB), "re_run_query", sql=CANDIDATES)
    assert {r[1] for r in bob["preview"]} == {"PRJ-Y"}
    _, joined = await call(tools, who("data"), "re_run_query", sql="SELECT COUNT(*) FROM unit_diagnostic_causes c"
                           " JOIN dim_unit_master m USING (unit_key) WHERE m.project_key <> 'PRJ-X'")
    assert joined["preview"] == [[0]]
    err, text = await call(tools, who("data"), "re_run_query", sql="SELECT * FROM main.dim_unit_master")
    assert err and "prohibited" in text


async def test_re_run_query_time_limit(tools: McpTools) -> None:
    err, text = await call(tools, who("data"), "re_run_query",
                           sql="WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c")
    assert err and "time limit" in text


async def test_re_list_and_describe_use_scoped_rows(tools: McpTools) -> None:
    _, tables = await call(tools, who("data"), "re_list_tables")
    names = {t["name"] for t in tables["tables"]}
    assert "fact_unit_inventory_snapshot" in names and "semantic_config" in names
    _, described = await call(tools, who("data"), "re_describe_table", table="dim_project_profile", sample_rows=10)
    assert [r[0] for r in described["sample_rows"]] == ["PRJ-X"]
    err, _ = await call(tools, who("data"), "re_describe_table", table="nope")
    assert err


async def test_re_tools_without_a_configured_warehouse_say_so(tmp_path: Path) -> None:
    built, db = await build_tools(tmp_path)
    try:
        err, text = await call(built, who("data"), "re_list_tables")
        assert err and "re_warehouse_db" in text
    finally:
        await db.dispose()


def test_mcp_identity_carries_the_task_so_artifacts_file_under_the_run() -> None:
    from vdagent_backend.core import TokenRegistry

    registry = TokenRegistry()
    identity = registry.resolve(registry.issue(ALICE, "data", "inv_1", "t_42"))
    assert identity is not None and identity.task_id == "t_42"
    legacy = registry.resolve(registry.issue(ALICE, "data", "inv_2"))
    assert legacy is not None and legacy.task_id == ""
