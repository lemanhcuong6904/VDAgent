"""This plugin's own behaviour. EDIT: replace with tests for your agent."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from vdagent_sdk import Agent, McpEndpoint, Message, ToolCall

from .. import setup
from ..agent import EchoAgent


@dataclass
class FakeAPI:
    """Records what `setup` registers (the Backend's PluginAPI does the same, plus validation)."""

    plugin: str = "agent_template"
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("test"))
    agents: dict[str, tuple[str, Agent]] = field(default_factory=dict)
    hooks: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        self.agents[name] = (description, agent)

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        self.hooks.append(fn)


@dataclass
class FakeContext:
    history: list[Message]
    steps: list[tuple[str, list[ToolCall]]] = field(default_factory=list)
    invocation_id: str = "inv_1"
    task_id: str = "t_1"
    user_id: str = "u_1"
    summary: str = ""
    peers: list[Any] = field(default_factory=list)
    mcp: McpEndpoint = McpEndpoint("http://mcp.test/mcp", "token")
    max_steps: int = 12

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        self.steps.append((content, list(tool_calls)))

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        raise AssertionError("the echo agent calls no tools")

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        raise AssertionError("the echo agent calls no agents")


def test_setup_registers_the_echo_agent_under_the_configured_name() -> None:
    api = FakeAPI()
    setup(api, {"name": "parrot"})
    ((name, (description, agent)),) = api.agents.items()
    assert name == "parrot" and description and isinstance(agent, EchoAgent)

    default = FakeAPI()
    setup(default, {})
    assert list(default.agents) == ["echo"]


async def test_echo_replies_with_the_inbound_message() -> None:
    ctx = FakeContext(history=[{"role": "user", "content": "[from: user] revenue by region?"}])
    await EchoAgent().invoke(ctx)
    assert ctx.steps == [("echo: [from: user] revenue by region?", [])]


async def test_compact_keeps_the_newest_2000_chars_of_summary_and_inbound_messages() -> None:
    agent = EchoAgent()
    summary = await agent.compact(
        "- earlier",
        [
            {"role": "user", "content": "[from: user] hi"},
            {"role": "assistant", "content": "echo: [from: user] hi"},
            {"role": "user", "content": "[from: data] " + "x" * 3000},
        ],
    )
    assert len(summary) == 2000
    assert summary.endswith("x" * 1987)
    short = await agent.compact("", [{"role": "user", "content": "[from: user] hi"}])
    assert short == "[from: user] hi"
