"""The plugin entry and the LangGraph turn (agent → tools → assess → finalize), driven through a
recording `ctx` with a scripted chat model, a scripted judge and a fake MCP session."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from vdagent_sdk import Agent, AgentTimeoutError, McpEndpoint, Message, Peer, PluginConfigError, ToolCall

from .. import setup
from ..agent import DESCRIPTION, NAME, STEP_LIMIT_TEXT, LangGraphAgent, build_agent
from ..judge import REVIEW, Verdict
from ..mcp_client import MAX_TOOL_RESULT_CHARS, TRUNCATION_MARKER, McpSession, McpTool, ToolOutcome
from ..settings import load_settings, read_env

SYSTEM_PROMPT = "You are the test agent."
COMPACT_PROMPT = "Summarise the conversation."
LLM_ENV = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://llm", "LLM_MODEL": "m"}
INBOUND = "[from: orchestrator] chart revenue by region"
PEERS = [
    Peer("data", "Queries the warehouse; returns dataset ids."),
    Peer("compare", "Compares datasets, periods and segments."),
]
PASS = Verdict(acceptable=0.9, problem="none")

Script = AIMessage | Exception


@dataclass
class ChatCall:
    messages: list[BaseMessage]
    tools: list[dict[str, Any]]

    @property
    def system(self) -> str:
        first = self.messages[0]
        return str(first.content) if isinstance(first, SystemMessage) else ""


@dataclass
class Recorder:
    """Scripted replies in order (the last entry repeats); every request is recorded."""

    script: Sequence[Script]
    calls: list[ChatCall] = field(default_factory=list)


class ScriptedChat(BaseChatModel):
    rec: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> Any:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

    def _reply(self, messages: list[BaseMessage], tools: list[dict[str, Any]]) -> ChatResult:
        rec: Recorder = self.rec
        rec.calls.append(ChatCall(list(messages), tools))
        entry = rec.script[min(len(rec.calls), len(rec.script)) - 1]
        if isinstance(entry, Exception):
            raise entry
        return ChatResult(generations=[ChatGeneration(message=entry.model_copy(update={"id": None}))])

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        return self._reply(messages, kw.get("tools", []))

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        return self._reply(messages, kw.get("tools", []))


def chat(*script: Script) -> tuple[ScriptedChat, Recorder]:
    rec = Recorder(list(script))
    return ScriptedChat(rec=rec), rec


def ai(content: str = "", *calls: tuple[str | None, str, dict[str, Any]]) -> AIMessage:
    return AIMessage(content=content, tool_calls=[{"id": i, "name": n, "args": a, "type": "tool_call"} for i, n, a in calls])


@dataclass
class ScriptedJudge:
    """Verdicts in order (the last repeats); records what it was asked to assess."""

    verdicts: Sequence[Verdict] = (PASS,)
    asked: list[tuple[str, str, list[str]]] = field(default_factory=list)

    async def assess(self, request: str, answer: str, artifacts: Sequence[str]) -> Verdict:
        self.asked.append((request, answer, list(artifacts)))
        return self.verdicts[min(len(self.asked), len(self.verdicts)) - 1]


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

    history: list[Message] = field(default_factory=lambda: [{"role": "user", "content": INBOUND}])
    summary: str = ""
    max_steps: int = 12
    peers: list[Peer] = field(default_factory=lambda: list(PEERS))
    mcp: McpEndpoint = McpEndpoint("http://localhost:8000/mcp", "tok-123")
    invocation_id: str = "inv_1"
    task_id: str = "t_1"
    user_id: str = "u_1"
    memory: Any = None
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

    def answers(self) -> list[str]:
        return [content for kind, content, calls in self.events if kind == "assistant" and not calls]


@dataclass
class FakeAPI:
    agents: dict[str, tuple[str, Agent]] = field(default_factory=dict)
    plugin: str = "test"
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("test"))

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        self.agents[name] = (description, agent)

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        raise AssertionError("this plugin registers no shutdown hook")


MAKE_CHART = McpTool(
    name="make_chart",
    description="Render a chart from a dataset.",
    input_schema={"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]},
)


def make_agent(model: ScriptedChat, mcp: FakeMcp, judge: ScriptedJudge | None = None) -> LangGraphAgent:
    return LangGraphAgent(
        model=model,
        judge=judge or ScriptedJudge(),
        mcp_session_factory=mcp.factory,
        system_prompt=SYSTEM_PROMPT,
        compact_prompt=COMPACT_PROMPT,
    )


def api_timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "http://llm/chat/completions"))


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
    assert (name, description) == (NAME, DESCRIPTION) and isinstance(agent, LangGraphAgent)


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
    settings = load_settings({**env, "LLM_MODEL": "m"})
    assert (settings.llm_timeout_s, settings.judge_model, settings.jev_decisions_url) == (
        120.0,
        "typesafe/jev-1.13",
        "https://openrouter.ai/api/alpha/decisions",
    )
    custom = load_settings({**env, "LLM_MODEL": "m", "JUDGE_MODEL": " j ", "JEV_DECISIONS_URL": " http://jev "})
    assert (custom.judge_model, custom.jev_decisions_url) == ("j", "http://jev")


def test_build_agent_reports_missing_configuration() -> None:
    with pytest.raises(PluginConfigError, match="OPENAI_BASE_URL"):
        build_agent({"OPENAI_API_KEY": "k"})


# --------------------------------------------------------------------------- the graph: agent ⇄ tools


async def test_last_step_has_no_tools_and_a_model_ignoring_that_yields_the_step_limit_text() -> None:
    model, rec = chat(ai("", ("c", "make_chart", {"dataset_id": "ds_1"})))  # keeps asking for tools
    mcp = FakeMcp(tools=[MAKE_CHART], handlers={"make_chart": lambda a: ToolOutcome("ch_1")})
    ctx = RecordingContext(max_steps=3)
    await make_agent(model, mcp).invoke(ctx)

    assert [len(c.tools) > 0 for c in rec.calls] == [True, True, False]
    assert ctx.kinds() == ["assistant", "tool", "assistant", "tool", "assistant"]
    assert ctx.events[-1] == ("assistant", STEP_LIMIT_TEXT, [])


async def test_concurrent_send_to_agent_calls_each_await_their_own_result() -> None:
    model, rec = chat(
        ai(
            "Asking both.",
            ("tc_a", "send_to_agent", {"agent": "data", "message": "revenue by region 2025"}),
            ("tc_b", "send_to_agent", {"agent": "compare", "message": "compare ds_1 vs ds_2"}),
        ),
        ai("Chart ch_9 saved."),
    )
    loop = asyncio.get_running_loop()
    ctx = RecordingContext(replies={"tc_a": loop.create_future(), "tc_b": loop.create_future()})
    turn = asyncio.create_task(make_agent(model, FakeMcp(tools=[], handlers={})).invoke(ctx))

    await _until(lambda: len(ctx.calls) == 2)
    assert ctx.events == [("assistant", "Asking both.", ["tc_a", "tc_b"])]
    ctx.replies["tc_b"].set_result("ds_9")
    await _until(lambda: "tc_b" in ctx.tool_results())
    assert "tc_a" not in ctx.tool_results()
    ctx.replies["tc_a"].set_result("error: calling data would deadlock")
    await turn

    assert ctx.events[-1] == ("assistant", "Chart ch_9 saved.", [])
    tool_messages = {m.tool_call_id: m.content for m in rec.calls[1].messages if isinstance(m, ToolMessage)}
    assert tool_messages == {"tc_a": "error: calling data would deadlock", "tc_b": "ds_9"}


async def test_mcp_results_are_emitted_and_the_first_request_carries_prompt_history_and_tools() -> None:
    big = "x" * (MAX_TOOL_RESULT_CHARS + 500)
    model, rec = chat(
        ai("", ("q1", "make_chart", {"dataset_id": "ds_1"}), ("q2", "make_chart", {"dataset_id": "ds_2"})),
        ai("Done: ch_1."),
    )
    results = {"ds_1": "ch_1", "ds_2": big}
    mcp = FakeMcp(tools=[MAKE_CHART], handlers={"make_chart": lambda a: ToolOutcome(results[a["dataset_id"]])})
    ctx = RecordingContext(
        summary="User prefers EUR.",
        history=[
            {"role": "user", "content": "[from: user] earlier"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": INBOUND},
        ],
    )
    await make_agent(model, mcp).invoke(ctx)

    assert mcp.opened_with == [("http://localhost:8000/mcp", "tok-123")]
    assert ctx.tool_results() == {"q1": "ch_1", "q2": big[:MAX_TOOL_RESULT_CHARS] + TRUNCATION_MARKER}
    first = rec.calls[0]
    assert first.system == f"{SYSTEM_PROMPT}\n\n## Summary of earlier work with this user\nUser prefers EUR."
    assert [(type(m).__name__, m.content) for m in first.messages[1:]] == [
        ("HumanMessage", "[from: user] earlier"),
        ("AIMessage", "ok"),
        ("HumanMessage", INBOUND),
    ]
    tools = {t["function"]["name"]: t["function"] for t in first.tools}
    assert tools["make_chart"]["parameters"] == MAKE_CHART.input_schema
    assert tools["send_to_agent"]["parameters"]["properties"]["agent"]["enum"] == ["data", "compare"]


async def test_tool_failures_become_error_tool_content_and_the_turn_continues() -> None:
    def failing(args: dict[str, Any]) -> ToolOutcome:
        if args["dataset_id"] == "boom":
            raise ConnectionError("MCP connection reset")
        return ToolOutcome("unknown dataset", is_error=True)

    model, _ = chat(
        ai(
            "",
            ("e1", "make_chart", {"dataset_id": "ds_x"}),
            ("e2", "make_chart", {"dataset_id": "boom"}),
            ("e4", "drop_database", {}),
            ("e5", "send_to_agent", {"agent": "data"}),
        ),
        ai("I could not chart that."),
    )
    ctx = RecordingContext()
    await make_agent(model, FakeMcp(tools=[MAKE_CHART], handlers={"make_chart": failing})).invoke(ctx)

    results = ctx.tool_results()
    assert results["e1"] == "error: unknown dataset"
    assert results["e2"].startswith("error:") and "MCP connection reset" in results["e2"]
    assert results["e4"] == "error: unknown tool 'drop_database'"
    assert results["e5"] == "error: send_to_agent requires a non-empty 'message'"
    assert ctx.events[-1] == ("assistant", "I could not chart that.", [])


async def test_tool_calls_without_ids_get_unique_ids_used_for_their_results() -> None:
    model, _ = chat(ai("", (None, "make_chart", {"dataset_id": "a"}), (None, "make_chart", {"dataset_id": "b"})), ai("done"))
    ctx = RecordingContext()
    mcp = FakeMcp(tools=[MAKE_CHART], handlers={"make_chart": lambda a: ToolOutcome(a["dataset_id"])})
    await make_agent(model, mcp).invoke(ctx)

    _, _, ids = ctx.events[0]
    assert len(set(ids)) == 2 and all(ids)
    assert sorted(ctx.tool_results()) == sorted(ids)


async def test_model_timeout_is_agent_timeout_and_other_failures_propagate() -> None:
    timeout, _ = chat(api_timeout())
    with pytest.raises(AgentTimeoutError):
        await make_agent(timeout, FakeMcp([], {})).invoke(RecordingContext())
    broken, _ = chat(RuntimeError("provider returned 500"))
    with pytest.raises(RuntimeError, match="provider returned 500"):
        await make_agent(broken, FakeMcp([], {})).invoke(RecordingContext())


# --------------------------------------------------------------------------- the graph: quality gate


async def test_an_accepted_draft_is_emitted_once_as_the_final_answer() -> None:
    model, _ = chat(ai("", ("c1", "make_chart", {"dataset_id": "ds_1"})), ai("Chart ch_7 of ds_1; report rp_3."))
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(tools=[MAKE_CHART], handlers={"make_chart": lambda a: ToolOutcome('{"chart_id": "ch_7", "report": "rp_3"}')})
    ctx = RecordingContext()
    await make_agent(model, mcp, judge).invoke(ctx)

    assert judge.asked == [(INBOUND, "Chart ch_7 of ds_1; report rp_3.", ["ch_7", "rp_3"])]
    assert ctx.kinds() == ["assistant", "tool", "assistant"]
    assert ctx.answers() == ["Chart ch_7 of ds_1; report rp_3."]


async def test_a_rejected_draft_is_revised_with_the_problem_specific_review_and_only_the_revision_is_emitted() -> None:
    model, rec = chat(ai("Chart ch_1 for 2025."), ai("Chart ch_1 for 2025 and ch_2 for 2024."))
    judge = ScriptedJudge([Verdict(acceptable=0.2, problem="missing_part"), PASS])
    ctx = RecordingContext()
    await make_agent(model, FakeMcp([], {}), judge).invoke(ctx)

    assert ctx.events == [("assistant", "Chart ch_1 for 2025 and ch_2 for 2024.", [])]
    revision_request = rec.calls[1].messages
    assert [type(m).__name__ for m in revision_request[-2:]] == ["AIMessage", "HumanMessage"]
    assert revision_request[-2].content == "Chart ch_1 for 2025."
    assert REVIEW["missing_part"] in str(revision_request[-1].content)
    assert [answer for _, answer, _ in judge.asked] == ["Chart ch_1 for 2025.", "Chart ch_1 for 2025 and ch_2 for 2024."]


async def test_there_is_at_most_one_revision() -> None:
    model, rec = chat(ai("draft 1"), ai("draft 2"), ai("draft 3"))
    judge = ScriptedJudge([Verdict(acceptable=0.1, problem="unclear")])
    ctx = RecordingContext()
    await make_agent(model, FakeMcp([], {}), judge).invoke(ctx)

    assert len(rec.calls) == 2 and len(judge.asked) == 2
    assert ctx.events == [("assistant", "draft 2", [])]


async def test_no_revision_when_the_step_budget_is_spent() -> None:
    model, rec = chat(ai("", ("c1", "make_chart", {"dataset_id": "ds_1"})), ai("only draft"))
    judge = ScriptedJudge([Verdict(acceptable=0.1, problem="no_numbers")])
    ctx = RecordingContext(max_steps=2)
    await make_agent(model, FakeMcp([MAKE_CHART], {"make_chart": lambda a: ToolOutcome("ch_1")}), judge).invoke(ctx)

    assert len(rec.calls) == 2 and len(judge.asked) == 1
    assert ctx.answers() == ["only draft"]


# --------------------------------------------------------------------------- compaction


async def test_compact_summarises_with_the_compact_prompt() -> None:
    model, rec = chat(ai("  - User wants EUR.\n- ds_1: revenue by region 2025  "))
    summary = await make_agent(model, FakeMcp([], {})).compact(
        "- Earlier: ds_0 is 2024 revenue.",
        [
            {"role": "user", "content": "[from: user] use EUR please"},
            {"role": "assistant", "content": "Here is ds_1."},
            {"role": "tool", "tool_call_id": "c1", "content": "y" * 2500},
        ],
    )
    assert summary == "- User wants EUR.\n- ds_1: revenue by region 2025"
    (only,) = rec.calls
    assert only.tools == [] and only.system == COMPACT_PROMPT
    rendered = str(only.messages[1].content)
    assert "ds_0 is 2024 revenue" in rendered and "[from: user] use EUR please" in rendered
    assert "y" * 2000 + "…[truncated]" in rendered and "y" * 2001 not in rendered


async def test_compact_timeout_is_agent_timeout() -> None:
    model, _ = chat(api_timeout())
    with pytest.raises(AgentTimeoutError):
        await make_agent(model, FakeMcp([], {})).compact("", [])
