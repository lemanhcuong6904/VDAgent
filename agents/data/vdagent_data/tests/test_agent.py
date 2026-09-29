"""The plugin entry and the LiteLLM tool loop, driven through a recording `ctx` with a scripted LLM
and a fake MCP session."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from vdagent_sdk import Agent, AgentTimeoutError, McpEndpoint, Message, Peer, PluginConfigError, ToolCall

from .. import setup
from ..agent import DESCRIPTION, NAME, LiteLLMAgent, build_agent
from ..llm import AssistantMessage, LLMTimeoutError
from ..mcp_client import MAX_TOOL_RESULT_CHARS, TRUNCATION_MARKER, McpSession, McpTool, ToolOutcome
from ..settings import load_settings, read_env

SYSTEM_PROMPT = "You are the test agent."
COMPACT_PROMPT = "Summarise the conversation."
LLM_ENV = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://llm", "LLM_MODEL": "m"}
PEERS = [
    Peer("data", "Queries the warehouse; returns dataset ids."),
    Peer("compare", "Compares datasets, periods and segments."),
]

Script = AssistantMessage | Exception | Callable[[list[dict[str, Any]], list[dict[str, Any]], str], AssistantMessage]


@dataclass
class LLMCall:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_choice: str


@dataclass
class ScriptedLLM:
    """Returns scripted replies in order; the last entry repeats once the script is exhausted."""

    script: Sequence[Script]
    calls: list[LLMCall] = field(default_factory=list)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str):
        self.calls.append(LLMCall(json.loads(json.dumps(messages)), tools, tool_choice))
        entry = self.script[min(len(self.calls), len(self.script)) - 1]
        if isinstance(entry, Exception):
            raise entry
        if callable(entry):
            return entry(messages, tools, tool_choice)
        return entry


@dataclass
class FakeMcp:
    tools: list[McpTool]
    handlers: dict[str, Callable[[dict[str, Any]], ToolOutcome]]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    opened_with: list[tuple[str, str]] = field(default_factory=list)

    async def list_tools(self) -> list[McpTool]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        return self.handlers[name](arguments)

    @asynccontextmanager
    async def factory(self, url: str, token: str) -> AsyncIterator[McpSession]:
        self.opened_with.append((url, token))
        yield self


@dataclass
class RecordingContext:
    """An `InvocationContext` that records every step; `call_agent` awaits `replies[tool_call_id]`."""

    history: list[Message] = field(default_factory=lambda: [{"role": "user", "content": "[from: user] revenue by region?"}])
    summary: str = ""
    max_steps: int = 12
    peers: list[Peer] = field(default_factory=lambda: list(PEERS))
    mcp: McpEndpoint = McpEndpoint("http://localhost:8000/mcp", "tok-123")
    invocation_id: str = "inv_1"
    task_id: str = "t_1"
    user_id: str = "u_1"
    replies: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    events: list[tuple[str, Any, Any]] = field(default_factory=list)
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        self.events.append(("assistant", content, [tc.id for tc in tool_calls]))

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        self.events.append(("tool", tool_call_id, content))

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        self.calls.append((tool_call_id, target, message))
        return await self.replies[tool_call_id]

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.events]

    def tool_results(self) -> dict[str, str]:
        return {tcid: content for kind, tcid, content in self.events if kind == "tool"}


@dataclass
class FakeAPI:
    agents: dict[str, tuple[str, Agent]] = field(default_factory=dict)
    plugin: str = "test"
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("test"))

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        self.agents[name] = (description, agent)

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        raise AssertionError("this plugin registers no shutdown hook")


RUN_QUERY = McpTool(
    name="run_query",
    description="Run a read-only SELECT on the warehouse.",
    input_schema={"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
)


def tool_call(id: str, name: str, args: dict[str, Any] | str) -> ToolCall:
    return ToolCall(id=id, name=name, arguments_json=args if isinstance(args, str) else json.dumps(args))


def make_agent(llm: ScriptedLLM, mcp: FakeMcp) -> LiteLLMAgent:
    return LiteLLMAgent(
        llm=llm, mcp_session_factory=mcp.factory, system_prompt=SYSTEM_PROMPT, compact_prompt=COMPACT_PROMPT
    )


async def _until(probe: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not probe():
            await asyncio.sleep(0)


# --------------------------------------------------------------------------- plugin entry


def test_setup_registers_this_agent_built_from_the_plugin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[setup.__module__], "read_env", lambda: dict(LLM_ENV))
    api = FakeAPI()
    setup(api, {})
    ((name, (description, agent)),) = api.agents.items()
    assert (name, description) == (NAME, DESCRIPTION) and isinstance(agent, LiteLLMAgent)


def test_setup_fails_with_the_missing_variable_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[setup.__module__], "read_env", lambda: {})
    with pytest.raises(PluginConfigError, match="OPENAI_API_KEY"):
        setup(FakeAPI(), {})


def test_read_env_prefers_the_plugin_env_file_and_never_writes_os_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=from-file\nLLM_TIMEOUT_S=\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-process")
    monkeypatch.setenv("LLM_MODEL", "process-model")
    env = read_env(env_file)
    assert (env["OPENAI_API_KEY"], env["LLM_MODEL"], env["LLM_TIMEOUT_S"]) == ("from-file", "process-model", "")
    assert os.environ["OPENAI_API_KEY"] == "from-process"
    assert read_env(tmp_path / "missing.env")["OPENAI_API_KEY"] == "from-process"


def test_settings_name_the_missing_variable_and_default_the_timeout() -> None:
    env = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://llm"}
    with pytest.raises(PluginConfigError, match="LLM_MODEL"):
        load_settings(env)
    with pytest.raises(PluginConfigError, match="LLM_TIMEOUT_S"):
        load_settings({**env, "LLM_MODEL": "m", "LLM_TIMEOUT_S": "0"})
    assert load_settings({**env, "LLM_MODEL": "m"}).llm_timeout_s == 120.0


def test_build_agent_reports_missing_configuration() -> None:
    with pytest.raises(PluginConfigError, match="OPENAI_BASE_URL"):
        build_agent({"OPENAI_API_KEY": "k"})


# --------------------------------------------------------------------------- tool loop


async def test_terminates_at_max_steps_with_tool_choice_none_on_last_step() -> None:
    # A model that keeps asking for tools, even when told not to.
    llm = ScriptedLLM([AssistantMessage(content="", tool_calls=[tool_call("c", "run_query", {"sql": "SELECT 1"})])])
    mcp = FakeMcp(tools=[RUN_QUERY], handlers={"run_query": lambda a: ToolOutcome('{"dataset_id": "ds_1"}')})
    ctx = RecordingContext(max_steps=3)
    await make_agent(llm, mcp).invoke(ctx)

    assert [c.tool_choice for c in llm.calls] == ["auto", "auto", "none"]
    assert ctx.kinds() == ["assistant", "tool", "assistant", "tool", "assistant"]
    _, content, calls = ctx.events[-1]
    assert calls == [] and content != ""


async def test_concurrent_send_to_agent_calls_each_await_their_own_result() -> None:
    llm = ScriptedLLM(
        [
            AssistantMessage(
                content="Asking both.",
                tool_calls=[
                    tool_call("tc_a", "send_to_agent", {"agent": "data", "message": "revenue by region 2025"}),
                    tool_call("tc_b", "send_to_agent", {"agent": "compare", "message": "compare ds_1 vs ds_2"}),
                ],
            ),
            AssistantMessage(content="Revenue grew in every region (ds_9)."),
        ]
    )
    loop = asyncio.get_running_loop()
    ctx = RecordingContext(replies={"tc_a": loop.create_future(), "tc_b": loop.create_future()})
    turn = asyncio.create_task(make_agent(llm, FakeMcp(tools=[], handlers={})).invoke(ctx))

    await _until(lambda: len(ctx.calls) == 2)
    assert sorted(ctx.calls) == [
        ("tc_a", "data", "revenue by region 2025"),
        ("tc_b", "compare", "compare ds_1 vs ds_2"),
    ]
    ctx.replies["tc_b"].set_result("ds_9")
    await _until(lambda: "tc_b" in ctx.tool_results())
    assert "tc_a" not in ctx.tool_results()
    ctx.replies["tc_a"].set_result("error: calling data would deadlock")
    await turn

    assert ctx.events[-3:-1] == [("tool", "tc_b", "ds_9"), ("tool", "tc_a", "error: calling data would deadlock")]
    assert ctx.events[-1] == ("assistant", "Revenue grew in every region (ds_9).", [])
    tool_messages = {m["tool_call_id"]: m["content"] for m in llm.calls[1].messages if m["role"] == "tool"}
    assert tool_messages == {"tc_a": "error: calling data would deadlock", "tc_b": "ds_9"}


async def test_mcp_results_are_emitted_as_tool_results() -> None:
    big = "x" * (MAX_TOOL_RESULT_CHARS + 500)
    llm = ScriptedLLM(
        [
            AssistantMessage(
                content="",
                tool_calls=[
                    tool_call("q1", "run_query", {"sql": "SELECT region FROM dim_store"}),
                    tool_call("q2", "run_query", {"sql": "SELECT * FROM fact_sales"}),
                ],
            ),
            AssistantMessage(content="Done: ds_1."),
        ]
    )
    results = {"SELECT region FROM dim_store": '{"dataset_id": "ds_1"}', "SELECT * FROM fact_sales": big}
    mcp = FakeMcp(tools=[RUN_QUERY], handlers={"run_query": lambda a: ToolOutcome(results[a["sql"]])})
    ctx = RecordingContext(summary="User prefers EUR.")
    await make_agent(llm, mcp).invoke(ctx)

    assert mcp.opened_with == [("http://localhost:8000/mcp", "tok-123")]
    assert sorted(mcp.calls, key=lambda c: c[1]["sql"]) == [
        ("run_query", {"sql": "SELECT * FROM fact_sales"}),
        ("run_query", {"sql": "SELECT region FROM dim_store"}),
    ]
    tool_msgs = ctx.tool_results()
    assert tool_msgs["q1"] == '{"dataset_id": "ds_1"}'
    assert tool_msgs["q2"] == big[:MAX_TOOL_RESULT_CHARS] + TRUNCATION_MARKER

    first = llm.calls[0]
    assert first.messages[0] == {
        "role": "system",
        "content": f"{SYSTEM_PROMPT}\n\n## Summary of earlier work with this user\nUser prefers EUR.",
    }
    assert first.messages[1:] == [{"role": "user", "content": "[from: user] revenue by region?"}]
    tools = {t["function"]["name"]: t["function"] for t in first.tools}
    assert tools["run_query"]["parameters"] == RUN_QUERY.input_schema
    assert tools["send_to_agent"]["parameters"]["properties"]["agent"]["enum"] == ["data", "compare"]
    assert "- data: Queries the warehouse; returns dataset ids." in tools["send_to_agent"]["description"]


async def test_tool_failures_become_error_tool_content_and_the_turn_continues() -> None:
    def failing(args: dict[str, Any]) -> ToolOutcome:
        if args["sql"] == "boom":
            raise ConnectionError("MCP connection reset")
        return ToolOutcome("only SELECT statements are allowed", is_error=True)

    llm = ScriptedLLM(
        [
            AssistantMessage(
                content="",
                tool_calls=[
                    tool_call("e1", "run_query", {"sql": "INSERT INTO x VALUES (1)"}),
                    tool_call("e2", "run_query", {"sql": "boom"}),
                    tool_call("e3", "run_query", "{not json"),
                    tool_call("e4", "drop_database", {}),
                    tool_call("e5", "send_to_agent", {"agent": "data"}),
                ],
            ),
            AssistantMessage(content="I could not run that query."),
        ]
    )
    ctx = RecordingContext()
    await make_agent(llm, FakeMcp(tools=[RUN_QUERY], handlers={"run_query": failing})).invoke(ctx)

    tool_msgs = ctx.tool_results()
    assert tool_msgs["e1"] == "error: only SELECT statements are allowed"
    assert tool_msgs["e2"].startswith("error:") and "MCP connection reset" in tool_msgs["e2"]
    assert tool_msgs["e3"].startswith("error: invalid JSON arguments for 'run_query'")
    assert tool_msgs["e4"] == "error: unknown tool 'drop_database'"
    assert tool_msgs["e5"] == "error: send_to_agent requires a non-empty 'message'"
    assert ctx.events[-1] == ("assistant", "I could not run that query.", [])


async def test_llm_timeout_is_agent_timeout_and_other_failures_propagate() -> None:
    timeout = make_agent(ScriptedLLM([LLMTimeoutError("LLM call timed out after 120s")]), FakeMcp([], {}))
    with pytest.raises(AgentTimeoutError, match="timed out after 120s"):
        await timeout.invoke(RecordingContext())
    broken = make_agent(ScriptedLLM([RuntimeError("provider returned 500")]), FakeMcp([], {}))
    with pytest.raises(RuntimeError, match="provider returned 500"):
        await broken.invoke(RecordingContext())


# --------------------------------------------------------------------------- compaction


async def test_compact_summarises_with_the_compact_prompt() -> None:
    llm = ScriptedLLM([AssistantMessage(content="  - User wants EUR.\n- ds_1: revenue by region 2025  ")])
    summary = await make_agent(llm, FakeMcp([], {})).compact(
        "- Earlier: ds_0 is 2024 revenue.",
        [
            {"role": "user", "content": "[from: user] use EUR please"},
            {"role": "assistant", "content": "Here is ds_1."},
            {"role": "tool", "tool_call_id": "c1", "content": "y" * 2500},
        ],
    )
    assert summary == "- User wants EUR.\n- ds_1: revenue by region 2025"
    (only,) = llm.calls
    assert only.tool_choice == "none"
    assert only.messages[0] == {"role": "system", "content": COMPACT_PROMPT}
    rendered = only.messages[1]["content"]
    assert "ds_0 is 2024 revenue" in rendered and "[from: user] use EUR please" in rendered
    assert "Here is ds_1." in rendered
    assert "y" * 2000 + "…[truncated]" in rendered and "y" * 2001 not in rendered


async def test_compact_timeout_is_agent_timeout() -> None:
    agent = make_agent(ScriptedLLM([LLMTimeoutError("LLM call timed out after 120s")]), FakeMcp([], {}))
    with pytest.raises(AgentTimeoutError):
        await agent.compact("", [])
