"""WS2 at the plugin boundary: a StepSpec@1 message runs the deterministic path, with or without an LLM."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from vdagent_data.tests.conftest import ALICE
from vdagent_data.tests.test_steps import step
from vdagent_backend.mcp.tools import McpTools
from vdagent_backend.tokens import McpIdentity
from vdagent_contracts.reports import AgentReport, parse_agent_report
from vdagent_data.agent import DataAgent, build_agent
from vdagent_data.mcp_client import McpSession, McpTool, ToolOutcome
from vdagent_sdk import McpEndpoint, PluginConfigError


class InProcessSession:
    def __init__(self, tools: McpTools, identity: McpIdentity) -> None:
        self._tools, self._identity = tools, identity

    async def list_tools(self) -> list[McpTool]:
        return [McpTool(name=t.name, description=t.description or "", input_schema=dict(t.inputSchema)) for t in self._tools.list_for("data")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        result = await self._tools.call(self._identity, name, arguments)
        return ToolOutcome(text=result.content[0].text, is_error=bool(result.is_error))


class Ctx:
    def __init__(self, text: str) -> None:
        self.invocation_id, self.task_id, self.user_id = f"inv_{ALICE}", f"t_{ALICE}", ALICE
        self.summary, self.peers, self.max_steps = "", [], 12
        self.history = [{"role": "user", "content": f"[from: orchestrator] {text}"}]
        self.mcp = McpEndpoint(url="http://mcp.test/mcp", token="tok")
        self.steps: list[tuple[str, list[Any]]] = []

    async def emit_assistant(self, content: str, tool_calls: Any = ()) -> None:
        self.steps.append((content, list(tool_calls)))

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:  # pragma: no cover - not used here
        raise AssertionError("the deterministic path emits no tool calls")

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:  # pragma: no cover
        raise AssertionError("the deterministic path calls no peer")


def factory(tools: McpTools) -> Any:
    @asynccontextmanager
    async def open_session(url: str, token: str) -> AsyncIterator[McpSession]:
        yield InProcessSession(tools, McpIdentity(user_id=ALICE, agent="data", invocation_id=f"inv_{ALICE}", task_id=f"t_{ALICE}"))

    return open_session


def the_report(ctx: Ctx) -> AgentReport:
    [(content, calls)] = ctx.steps
    assert calls == []
    report = parse_agent_report(content)
    assert isinstance(report, AgentReport), report
    return report


async def test_stepspec_message_runs_without_an_llm(mcp_tools: McpTools) -> None:
    agent = DataAgent(llm=None, mcp_session_factory=factory(mcp_tools), system_prompt="x", compact_prompt="y")
    ctx = Ctx(step().model_dump_json())
    await agent.invoke(ctx)
    report = the_report(ctx)
    assert report.state == "completed" and report.step_id == "B1" and report.idempotency_key == "pl_ws2:B1"
    assert len(report.artifact_refs) == 3


async def test_invalid_stepspec_is_rejected_as_spec_issue(mcp_tools: McpTools) -> None:
    agent = DataAgent(llm=None, mcp_session_factory=factory(mcp_tools), system_prompt="x", compact_prompt="y")
    bad = json.loads(step().model_dump_json()) | {"step_id": "3"}
    ctx = Ctx(json.dumps(bad))
    await agent.invoke(ctx)
    report = the_report(ctx)
    assert report.state == "rejected" and report.error is not None and report.error.code == "INVALID_STEPSPEC"


async def test_other_contracts_are_rejected(mcp_tools: McpTools) -> None:
    agent = DataAgent(llm=None, mcp_session_factory=factory(mcp_tools), system_prompt="x", compact_prompt="y")
    ctx = Ctx(json.dumps({"contract": "ChartTask@1"}))
    await agent.invoke(ctx)
    report = the_report(ctx)
    assert report.state == "rejected" and report.error is not None and report.error.code == "UNSUPPORTED_CONTRACT"


async def test_free_text_without_llm_says_so(mcp_tools: McpTools) -> None:
    agent = DataAgent(llm=None, mcp_session_factory=factory(mcp_tools), system_prompt="x", compact_prompt="y")
    ctx = Ctx("doanh thu theo vùng năm 2025?")
    await agent.invoke(ctx)
    [(content, calls)] = ctx.steps
    assert calls == [] and "StepSpec@1" in content and "LLM" in content


def test_data_llm_off_builds_a_deterministic_agent_without_keys() -> None:
    agent = build_agent({"DATA_LLM": "off"})
    assert isinstance(agent, DataAgent) and agent.has_llm is False


def test_missing_llm_settings_still_fail_by_default() -> None:
    with pytest.raises(PluginConfigError, match="OPENAI_API_KEY"):
        build_agent({})
