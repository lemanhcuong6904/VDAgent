"""WS5 golden case through the REAL Backend engine: one user message to the Orchestrator runs
Data → [Insight ∥ Compare] → Chart automatically, with the real plugins and the real MCP tools (in-process).

Insight and Compare are wrapped by a barrier that only opens when both are running: the test would time out if the
Orchestrator dispatched them one after the other. No LLM, no demo data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.config import Config, load_config
from vdagent_backend.conversations import Messages, Tasks
from vdagent_backend.core import EventBus, TokenRegistry
from vdagent_backend.mcp import TOOLS, McpTools
from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.plugins import AgentRegistry, RegisteredAgent
from vdagent_backend.re_warehouse import build
from vdagent_backend.runtime import Engine
from vdagent_backend.scopes import UserScopes, seed_missing_demo_scopes
from vdagent_backend.warehouse import RealEstateWarehouse, Warehouse
from vdagent_agentkit.mcp_client import McpSession, McpTool, ToolOutcome
from vdagent_chart.agent import ChartPluginAgent
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.service import ChartAgentService
from vdagent_compare.agent import CompareAgent
REPORT_QUESTION = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."
from vdagent_data.agent import DataAgent
from vdagent_insight.bridge import InsightAgent
from vdagent_insight.runtime import build_runtime
from vdagent_orchestrator.agent import OrchestratorAgent
from vdagent_report.agent import ReportAgent
from vdagent_sdk import InvocationContext, Message

ALICE, BOB = "u_000000000001", "u_000000000002"
NOW = "2026-09-30T00:00:00.000Z"
# The MCP grants of each plugin entry in backend/config.yaml: the engine and the MCP tools apply them as in production.
GRANTS: dict[str, frozenset[str]] = {
    spec.module.removeprefix("vdagent_"): spec.mcp_tools
    for spec in load_config(Path(__file__).resolve().parents[4] / "backend" / "config.yaml").plugins
}
QUESTION = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng và vẽ biểu đồ."


class Session:
    def __init__(self, tools: McpTools, tokens: TokenRegistry, token: str) -> None:
        identity = tokens.resolve(token)
        assert identity is not None, "MCP token not issued by the engine"
        self._tools, self._identity = tools, identity

    async def list_tools(self) -> list[McpTool]:
        granted = GRANTS[self._identity.agent]
        return [McpTool(t.name, t.description or "", dict(t.input_schema)) for t in TOOLS if t.name in granted]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        result = await self._tools.call(self._identity, GRANTS[self._identity.agent], name, arguments)
        return ToolOutcome(text=result.content[0].text, is_error=bool(result.is_error))


class Barriered:
    """Delegates to a real agent, after every wrapped agent has started its turn."""

    def __init__(self, agent: Any, barrier: asyncio.Barrier, log: list[str], name: str) -> None:
        self._agent, self._barrier, self._log, self._name = agent, barrier, log, name

    async def invoke(self, ctx: InvocationContext) -> None:
        self._log.append(f"{self._name}:start")
        async with asyncio.timeout(10):
            await self._barrier.wait()
        await self._agent.invoke(ctx)
        self._log.append(f"{self._name}:end")

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        return await self._agent.compact(previous_summary, messages)


@pytest.fixture
async def system(tmp_path: Path, request: pytest.FixtureRequest) -> AsyncIterator[dict[str, Any]]:
    re_db = str(tmp_path / "re.db")
    build(re_db)
    cfg = Config(backend_db=str(tmp_path / "backend.db"), warehouse_db=str(tmp_path / "w.db"), mcp_public_url="http://mcp.test/mcp",
                 frontend_dist=str(tmp_path / "no-dist"), re_warehouse_db=re_db)
    await asyncio.to_thread(migrate, sqlite_url(cfg.backend_db))  # the Alembic migrations, as at Backend startup
    db = create_database(sqlite_url(cfg.backend_db))
    with sqlite3.connect(cfg.backend_db) as conn:
        conn.executemany("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", [(ALICE, "Alice", NOW), (BOB, "Bob", NOW)])
    conn.close()
    seed_missing_demo_scopes(cfg.backend_db)
    artifacts_service = ArtifactService(db)
    tokens = TokenRegistry()
    tools = McpTools(artifacts_service, Warehouse(cfg.warehouse_db, 5.0), re_warehouse=RealEstateWarehouse(re_db, 5.0),
                     scopes=UserScopes(db))

    @asynccontextmanager
    async def sessions(url: str, token: str) -> AsyncIterator[McpSession]:
        yield Session(tools, tokens, token)

    log: list[str] = []
    barrier = asyncio.Barrier(2)
    runtime = build_runtime({"INSIGHT_LLM": "off", "INSIGHT_ARTIFACT_SOURCE": "fixtures",
                             "INSIGHT_STORE_PATH": str(tmp_path / "insight.db")}, logging.getLogger("t"))
    planner_llm = None
    if getattr(request, "param", "offline") == "llm":
        from .test_llm_planner import GOLDEN, ScriptedLLM

        planner_llm = ScriptedLLM(json.dumps(GOLDEN))
    agents = {
        "orchestrator": OrchestratorAgent(llm=planner_llm, mcp_session_factory=sessions, system_prompt="x", compact_prompt="y",
                                          snapshot_id="SNAP-2026-09-28", semantic_config_version="sc-1"),
        "data": DataAgent(llm=None, mcp_session_factory=sessions, system_prompt="x", compact_prompt="y"),
        "insight": Barriered(InsightAgent(runtime, mcp_session_factory=sessions), barrier, log, "insight"),
        "compare": Barriered(CompareAgent(llm=None, mcp_session_factory=sessions), barrier, log, "compare"),
        "chart": ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False, mcp_session_factory=sessions),
        "report": ReportAgent(model=None, judge=None, mcp_session_factory=sessions,
                              system_prompt="x", compact_prompt="y"),
    }
    registry = AgentRegistry(RegisteredAgent(n, f"{n} agent", a, "tests", GRANTS[n]) for n, a in agents.items())
    engine = Engine(cfg, db, EventBus(), tokens, registry, on_interrupted=artifacts_service.interrupt_run)
    await engine.recover()
    yield {"engine": engine, "db": db, "tools": tools, "log": log, "cfg": cfg, "planner_llm": planner_llm}
    await engine.stop()
    await db.dispose()


async def finish(system: dict[str, Any], agent: str, text: str, user: str = ALICE) -> tuple[dict[str, Any], str]:
    task, _ = await system["engine"].post_message(user, agent, text)
    async with asyncio.timeout(60):
        while (row := await Tasks(system["db"]).get_task(task["id"])) is None or row["status"] == "running":
            await asyncio.sleep(0.05)
    msgs = await Messages(system["db"]).messages_page(user, agent, None, 1000)
    final = [m for m in msgs if m["role"] == "assistant" and m["content"] and not m.get("tool_calls_json")][-1]["content"]
    return row, final


def artifacts(path: str) -> list[dict[str, Any]]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM artifacts ORDER BY created_at, artifact_id, version")]
    conn.close()
    return rows


async def test_golden_case_through_the_backend_engine(system: dict[str, Any]) -> None:
    task, answer = await finish(system, "orchestrator", QUESTION)
    assert task["status"] == "completed"

    # the orchestrator dispatched B1, then B2 + B3 together (they met at the barrier), then B4
    invs = await Tasks(system["db"]).list_task_invocations(task["id"])
    by_agent = {i["agent"]: i for i in invs}
    assert {"orchestrator", "data", "insight", "compare", "chart"} <= set(by_agent)
    assert all(i["status"] == "completed" for i in invs), [(i["agent"], i["status"], i.get("error")) for i in invs]
    log = system["log"]
    assert log[:2] in (["insight:start", "compare:start"], ["compare:start", "insight:start"])

    arts = artifacts(system["cfg"].backend_db)
    kinds = [a["artifact_type"] for a in arts if a["status"] != "SUPERSEDED" or a["artifact_type"] == "run_state"]
    for kind in ("dataset", "metric", "dq", "insight", "peer_definition", "comparison", "chart_spec", "run_state"):
        assert kind in kinds, kind
    dataset = next(a for a in arts if a["artifact_type"] == "dataset")
    ds_ref = {"artifact_id": dataset["artifact_id"], "artifact_type": "dataset", "content_hash": dataset["content_hash"], "version": 1}
    for a in arts:
        assert json.loads(a["snapshot_refs_json"]) == ["SNAP-2026-09-28"] and a["semantic_config_version"] == "sc-1", a["artifact_type"]
        if a["artifact_type"] in ("insight", "peer_definition", "comparison", "chart_spec"):
            assert ds_ref in json.loads(a["input_refs_json"])  # everything derives from the one dataset
    assert "PRJ-Y" not in " ".join(a["payload_json"] for a in arts if a["artifact_type"] != "dataset")
    assert not any(w in " ".join(a["payload_json"] for a in arts) for w in ("run_vhop_demo", "synthetic_", "metric_dom_target"))

    state = max((a for a in arts if a["artifact_type"] == "run_state"), key=lambda a: a["version"])
    steps = {s["step_id"]: s for s in json.loads(state["payload_json"])["steps"]}
    assert [steps[s]["status"] for s in ("B1", "B2", "B3", "B4")] == ["completed"] * 4
    assert steps["B2"]["input_refs"] == steps["B3"]["input_refs"] == steps["B1"]["output_refs"]

    comparison = json.loads(next(a for a in arts if a["artifact_type"] == "comparison")["payload_json"])
    metrics = {m["metric"]: m for m in comparison["metrics"]}
    assert (metrics["dom"]["subjectValue"], metrics["dom"]["benchmark"]["value"]) == (138, 61)
    assert (metrics["net_asking_price_per_m2"]["subjectValue"], metrics["net_asking_price_per_m2"]["benchmark"]["value"]) == (72500000, 64500000)
    for value in ("138", "61", "72.500.000", "64.500.000", "12,40"):
        assert value in answer, value
    assert re.search(r"B-11", answer)  # the peer set is flagged, not presented as the approved golden set


async def test_free_text_without_a_unit_is_not_forced_into_the_dag(system: dict[str, Any]) -> None:
    task, answer = await finish(system, "orchestrator", "doanh thu theo vùng năm 2025?")
    assert task["status"] == "completed" and "LLM" in answer
    invs = await Tasks(system["db"]).list_task_invocations(task["id"])
    assert {i["agent"] for i in invs} == {"orchestrator"}


async def test_unauthorized_user_gets_a_failed_run_not_prj_x_data(system: dict[str, Any]) -> None:
    task, answer = await finish(system, "orchestrator", QUESTION, user=BOB)
    assert (task["status"], task["outcome"]) == ("failed", "failed") and answer.startswith("Không hoàn thành")  # WS7 F-03
    assert "UNIT_NOT_FOUND" in answer
    arts = [a for a in artifacts(system["cfg"].backend_db) if a["user_id"] == BOB]
    assert {a["artifact_type"] for a in arts} == {"run_state"}

@pytest.mark.parametrize("system", ["offline", "llm"], indirect=True)
async def test_ws6_six_agent_report_through_the_backend_engine(system: dict[str, Any]) -> None:
    task, answer = await finish(system, "orchestrator", REPORT_QUESTION)
    assert task["status"] == "completed"
    invs = await Tasks(system["db"]).list_task_invocations(task["id"])
    assert {"orchestrator", "data", "insight", "compare", "chart", "report"} <= {i["agent"] for i in invs}
    assert all(i["status"] == "completed" for i in invs), [(i["agent"], i["status"], i.get("error")) for i in invs]
    assert system["log"][:2] in (["insight:start", "compare:start"], ["compare:start", "insight:start"])

    arts = artifacts(system["cfg"].backend_db)
    run_state = max((a for a in arts if a["artifact_type"] == "run_state"), key=lambda a: a["version"])
    plan = json.loads(run_state["payload_json"])["plan"]
    if system["planner_llm"] is not None:
        assert len(system["planner_llm"].calls) == 1
        assert plan["provenance"]["planner"] == "llm"
    else:
        assert "provenance" not in plan
    report = next(a for a in arts if a["artifact_type"] == "report")
    payload = json.loads(report["payload_json"])
    assert len(payload["sections"]) == 6
    assert len(payload["charts"]) >= 2 and len(payload["charts"]) + len(payload["tables"]) >= 2
    assert payload["validation"]["result"] == "pass"
    assert payload["validation"]["chart_bindings_checked"] > 0
    for value in ("138", "61", "72.500.000", "64.500.000", "12,40"):
        assert value in payload["markdown"] and value in answer
    assert all(json.loads(a["snapshot_refs_json"]) == ["SNAP-2026-09-28"] for a in arts)
    assert {a["semantic_config_version"] for a in arts} == {"sc-1"}

    dataset = next(a for a in arts if a["artifact_type"] == "dataset")
    dataset_ref = {"artifact_id": dataset["artifact_id"], "artifact_type": "dataset",
                   "content_hash": dataset["content_hash"], "version": dataset["version"]}
    assert dataset_ref in json.loads(report["input_refs_json"])
    by_ref = {f"{a['artifact_id']}@{a['version']}": json.loads(a["payload_json"]) for a in arts}

    def pointer(source_ref: str) -> Any:
        ref, path = source_ref.split("#", 1)
        value: Any = by_ref[ref]
        for token in path.split("/")[1:]:
            key = token.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value

    assert all(str(pointer(s["source_ref"])) == s["value_exact"] for s in payload["statements"])
    comparison = json.loads(next(a for a in arts if a["artifact_type"] == "comparison")["payload_json"])
    assert len(comparison["peerValues"]) - 1 == 5  # current approved engine result; B-11 remains blocked
    assert "B-11" in payload["sections"][5]["markdown"]

    with sqlite3.connect(system["cfg"].backend_db) as conn:
        saved = conn.execute("SELECT id, markdown FROM reports WHERE id = ?", (payload["delivery"]["report_id"],)).fetchone()
    assert saved is not None and saved[1] == payload["markdown"]
    assert all(f"{{{{chart_spec:{c['artifact_id']}@{c['version']}}}}}" in saved[1] for c in payload["charts"])

    state = max((a for a in arts if a["artifact_type"] == "run_state"), key=lambda a: a["version"])
    state_payload = json.loads(state["payload_json"])
    assert state_payload["waves"] == [["B1"], ["B2", "B3"], ["B4"], ["B5"]]
    assert {s["step_id"]: s["status"] for s in state_payload["steps"]} == {
        "B1": "completed", "B2": "completed", "B3": "completed", "B4": "completed", "B5": "completed",
    }
