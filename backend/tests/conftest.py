"""Engine / API test harness: five fake in-process agents that replay scripted turns.

Each fake agent implements the SDK `Agent` protocol and runs a per-test `handler(session)`
coroutine for every turn; the `Session` helpers are thin wrappers over the Backend's `ctx`, used
exactly like a real plugin uses it.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import pytest

from vdagent_backend.config import Config, PluginSpec
from vdagent_backend.db import repo
from vdagent_backend.db.database import create_db
from vdagent_backend.engine import Engine
from vdagent_backend.events import EventBus
from vdagent_backend.plugins import AgentRegistry, RegisteredAgent
from vdagent_backend.tokens import TokenRegistry
from vdagent_sdk import InvocationContext, Message, PluginAPI, ToolCall

ALICE, BOB = "u_000000000001", "u_000000000002"
AGENTS = ("orchestrator", "data", "compare", "insight", "report")
WAIT_S = 5.0

Call = tuple[str, str, dict[str, Any]]


class Session:
    """One fake turn, seen from the plugin side."""

    def __init__(self, ctx: InvocationContext) -> None:
        self.ctx = ctx
        self._n = 0

    @property
    def inbound(self) -> str:
        return self.ctx.history[-1]["content"]

    def _tcid(self) -> str:
        self._n += 1
        return f"{self.ctx.invocation_id}_c{self._n}"

    async def assistant(self, content: str = "", calls: list[Call] | None = None) -> None:
        await self.ctx.emit_assistant(content, [ToolCall(i, n, json.dumps(a)) for i, n, a in calls or []])

    async def tool(self, tool_call_id: str, content: str) -> None:
        await self.ctx.emit_tool_result(tool_call_id, content)

    async def call(self, tool_call_id: str, target: str, message: str) -> str:
        return await self.ctx.call_agent(tool_call_id, target, message)

    async def final(self, content: str) -> None:
        """The last assistant step (no tool calls); returning from the handler ends the turn."""
        await self.assistant(content)

    def send_to(self, target: str, message: str) -> Call:
        return (self._tcid(), "send_to_agent", {"agent": target, "message": message})

    async def ask(self, target: str, message: str) -> str:
        """One full send_to_agent step: assistant(tool_call) → call_agent → tool result."""
        tc = self.send_to(target, message)
        await self.assistant(calls=[tc])
        reply = await self.call(tc[0], target, message)
        await self.tool(tc[0], reply)
        return reply


Handler = Callable[[Session], Awaitable[None]]


async def _echo(session: Session) -> None:
    await session.final(f"done: {session.inbound}")


@dataclass
class FakeAgent:
    """An in-process `Agent` that runs `handler` for every turn and answers compactions."""

    name: str
    handler: Handler = _echo
    starts: list[InvocationContext] = field(default_factory=list)
    compacts: list[tuple[str, list[Message]]] = field(default_factory=list)
    compact_mode: Literal["ok", "raise", "hang"] = "ok"
    cancelled: list[str] = field(default_factory=list)  # invocation ids whose invoke saw CancelledError

    async def invoke(self, ctx: InvocationContext) -> None:
        self.starts.append(ctx)
        try:
            await self.handler(Session(ctx))
        except asyncio.CancelledError:
            self.cancelled.append(ctx.invocation_id)
            raise

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        self.compacts.append((previous_summary, messages))
        if self.compact_mode == "raise":
            raise RuntimeError("summariser down")
        if self.compact_mode == "hang":
            await asyncio.Event().wait()
        return f"SUMMARY#{len(self.compacts)}"


def registry_of(agents: Mapping[str, FakeAgent]) -> AgentRegistry:
    return AgentRegistry(RegisteredAgent(n, f"{n} agent", a, "tests") for n, a in agents.items())


def install_plugin(monkeypatch: pytest.MonkeyPatch, module: str, agents: Mapping[str, FakeAgent]) -> PluginSpec:
    """Make `module` importable as a plugin whose `setup` registers `agents`; returns its spec."""

    def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None:
        for name, agent in agents.items():
            api.register_agent(name=name, description=f"{name} agent", agent=agent)

    plugin = types.ModuleType(module)
    plugin.setup = setup  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module, plugin)
    return PluginSpec(module)


@dataclass
class Harness:
    cfg: Config
    db: Any
    bus: EventBus
    tokens: TokenRegistry
    registry: AgentRegistry
    engine: Engine
    agents: dict[str, FakeAgent]

    def on(self, agent: str, handler: Handler) -> None:
        self.agents[agent].handler = handler

    async def post(self, agent: str, content: str, user_id: str = ALICE) -> str:
        task, _ = await self.engine.post_message(user_id, agent, content)
        return task["id"]

    async def wait_task(self, task_id: str, status: str | None = None) -> dict[str, Any]:
        row = await wait_for(lambda: self._task_done(task_id))
        if status is not None:
            assert row["status"] == status, row
        return row

    async def _task_done(self, task_id: str) -> dict[str, Any] | None:
        row = await repo.get_task(self.db, task_id)
        return row if row and row["status"] != "running" else None

    async def invocations(self, task_id: str) -> list[dict[str, Any]]:
        return await repo.list_task_invocations(self.db, task_id)

    async def stack(self, agent: str, user_id: str = ALICE) -> list[dict[str, Any]]:
        return await repo.messages_page(self.db, user_id, agent, None, 1000)

    async def idle(self) -> None:
        """Wait until no invocation is queued or running."""
        await wait_for(lambda: self._idle())

    async def _idle(self) -> bool:
        return not await repo.inflight_invocations(self.db)


async def wait_for(probe: Callable[[], Awaitable[Any]], timeout: float = WAIT_S) -> Any:
    async with asyncio.timeout(timeout):
        while True:
            value = await probe()
            if value:
                return value
            await asyncio.sleep(0.01)


def seed_users(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name) VALUES (?, ?)", [(ALICE, "Alice"), (BOB, "Bob")])
    conn.close()


def make_config(tmp_path: Path, **overrides: Any) -> Config:
    cfg = Config(
        backend_db=str(tmp_path / "backend.db"),
        warehouse_db=str(tmp_path / "warehouse.db"),
        mcp_public_url="http://mcp.test/mcp",
        frontend_dist=str(tmp_path / "no-dist"),
        max_depth=4,
        max_steps=12,
    )
    return replace(cfg, **overrides)


@pytest.fixture
def fake_agents() -> dict[str, FakeAgent]:
    return {name: FakeAgent(name) for name in AGENTS}


@pytest.fixture
def cfg_overrides() -> dict[str, Any]:
    return {}


@pytest.fixture
async def harness(tmp_path: Path, fake_agents: dict[str, FakeAgent], cfg_overrides: dict[str, Any]) -> AsyncIterator[Harness]:
    cfg = make_config(tmp_path, **cfg_overrides)
    db = create_db(cfg.backend_db)
    seed_users(cfg.backend_db)
    bus, tokens = EventBus(), TokenRegistry()
    registry = registry_of(fake_agents)
    engine = Engine(cfg, db, bus, tokens, registry)
    await engine.start()
    yield Harness(cfg, db, bus, tokens, registry, engine, fake_agents)
    await engine.stop()
    await db.dispose()
