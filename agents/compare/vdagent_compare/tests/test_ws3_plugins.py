"""WS3 at the plugin boundary: a StepSpec@1 message reaches the structured path of Insight and Compare through MCP."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from vdagent_agentkit.mcp_client import McpSession, McpTool, ToolOutcome
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_backend.core import McpIdentity
from vdagent_compare.agent import CompareAgent
from vdagent_compare.tests.test_dw_integration import compare_step, data_refs
from vdagent_contracts.reports import AgentReport, parse_agent_report
from vdagent_data.tests.conftest import ALICE, McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_data.tests.test_agent_steps import Ctx
from vdagent_insight.bridge import InsightAgent
from vdagent_insight.runtime import build_runtime
from vdagent_insight.tests.test_dw_integration import insight_step


class Session:
    def __init__(self, tools: McpTools, agent: str) -> None:
        self._tools = tools
        self._identity = McpIdentity(user_id=ALICE, agent=agent, invocation_id=f"inv_{ALICE}_{agent}", task_id=f"t_{ALICE}")

    async def list_tools(self) -> list[McpTool]:
        return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        result = await self._tools.call(self._identity, name, arguments)
        return ToolOutcome(text=result.content[0].text, is_error=bool(result.is_error))


def factory(tools: McpTools, agent: str) -> Any:
    @asynccontextmanager
    async def open_session(url: str, token: str) -> AsyncIterator[McpSession]:
        yield Session(tools, agent)

    return open_session


def report_of(ctx: Ctx) -> AgentReport:
    content, calls = ctx.steps[-1]
    report = parse_agent_report(content)
    assert isinstance(report, AgentReport), content
    return report


async def test_insight_plugin_serves_stepspec(alice: McpPort, mcp_tools: McpTools, tmp_path: Path) -> None:
    refs = await data_refs(alice)
    runtime = build_runtime({"INSIGHT_LLM": "off", "INSIGHT_ARTIFACT_SOURCE": "fixtures",
                             "INSIGHT_STORE_PATH": str(tmp_path / "i.db")}, logging.getLogger("t"))
    agent = InsightAgent(runtime, mcp_session_factory=factory(mcp_tools, "insight"))
    ctx = Ctx(insight_step(refs).model_dump_json())
    await agent.invoke(ctx)
    report = report_of(ctx)
    assert report.state == "completed" and [r.artifact_type.value for r in report.artifact_refs] == ["insight"]


async def test_compare_plugin_serves_stepspec(alice: McpPort, mcp_tools: McpTools) -> None:
    refs = await data_refs(alice)
    agent = CompareAgent(llm=None, mcp_session_factory=factory(mcp_tools, "compare"))
    ctx = Ctx(compare_step(refs).model_dump_json())
    await agent.invoke(ctx)
    report = report_of(ctx)
    assert report.state == "completed"
    assert [r.artifact_type.value for r in report.artifact_refs] == ["peer_definition", "comparison"]


async def test_plugins_reject_other_contracts(mcp_tools: McpTools, tmp_path: Path) -> None:
    runtime = build_runtime({"INSIGHT_LLM": "off", "INSIGHT_ARTIFACT_SOURCE": "fixtures",
                             "INSIGHT_STORE_PATH": str(tmp_path / "i.db")}, logging.getLogger("t"))
    for agent in (InsightAgent(runtime, mcp_session_factory=factory(mcp_tools, "insight")),
                  CompareAgent(llm=None, mcp_session_factory=factory(mcp_tools, "compare"))):
        ctx = Ctx(json.dumps({"contract": "ChartTask@1"}))
        await agent.invoke(ctx)
        report = report_of(ctx)
        assert report.state == "rejected" and report.error is not None and report.error.code == "UNSUPPORTED_CONTRACT"
