"""The shared Backend test harness.

- `FakeAgent`: an in-process SDK `Agent` that runs a per-test `handler(session)` for every turn; the
  `Session` helpers are thin wrappers over the Backend's `ctx`, used exactly like a real plugin.
- `Harness` (fixture `harness`): a migrated database, the `Engine` and five fake agents.
- `app_client(cfg)`: an HTTP client on the real app with its lifespan running.
- Databases: `migrated_database`, `seed_users`, `build_legacy_db` (a pre-Alembic database).
- `make_config`, `wait_for`.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from vdagent_backend.app import create_app
from vdagent_backend.config import Config, PluginSpec
from vdagent_backend.conversations import Messages, Tasks
from vdagent_backend.core import EventBus, TokenRegistry
from vdagent_backend.runtime import Engine
from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.plugins import AgentRegistry, RegisteredAgent
from vdagent_sdk import InvocationContext, Message, PluginAPI, ToolCall

ALICE, BOB = "u_000000000001", "u_000000000002"
AGENTS = ("orchestrator", "data", "compare", "insight", "report")
WAIT_S = 5.0


@asynccontextmanager
async def app_client(cfg: Config) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client on `create_app(cfg)` with its lifespan running; `client.app` is the app."""
    app = create_app(cfg)
    # The lifespan owns anyio task groups: enter and exit it from one dedicated task.
    ready, stop = asyncio.Event(), asyncio.Event()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    runner = asyncio.create_task(run_lifespan())
    await asyncio.wait_for(ready.wait(), 10)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
    finally:
        stop.set()
        await runner


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

    @property
    def tasks(self) -> Tasks:
        return Tasks(self.db)

    @property
    def messages(self) -> Messages:
        return Messages(self.db)

    async def _task_done(self, task_id: str) -> dict[str, Any] | None:
        row = await self.tasks.get_task(task_id)
        return row if row and row["status"] != "running" else None

    async def invocations(self, task_id: str) -> list[dict[str, Any]]:
        return await self.tasks.list_task_invocations(task_id)

    async def stack(self, agent: str, user_id: str = ALICE) -> list[dict[str, Any]]:
        return await self.messages.messages_page(user_id, agent, None, 1000)


async def wait_for(probe: Callable[[], Awaitable[Any]], timeout: float = WAIT_S) -> Any:
    async with asyncio.timeout(timeout):
        while True:
            value = await probe()
            if value:
                return value
            await asyncio.sleep(0.01)


NOW = "2026-09-29T00:00:00.000000Z"  # created_at for rows inserted with raw SQL


def seed_users(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", [(ALICE, "Alice", NOW), (BOB, "Bob", NOW)])
    conn.close()


async def migrated_database(path: str) -> Any:
    """Migrate the SQLite file at `path` to head and return an `AsyncEngine` on it."""
    url = sqlite_url(path)
    await asyncio.to_thread(migrate, url)
    return create_database(url)


LEGACY_SCHEMA = Path(__file__).resolve().parent / "fixtures" / "legacy_schema.sql"
LEGACY_TASK, LEGACY_DATASET = "t_legacy000001", "ds_legacy00001"


def build_legacy_db(path: str) -> None:
    """A pre-Alembic backend.db (old `schema.sql`, its `strftime` defaults) holding one finished task
    of Alice's with a delegation step, a dataset and a memory note."""
    calls = json.dumps([{"id": "c1", "name": "send_to_agent", "arguments_json": "{}"}])
    with sqlite3.connect(path) as conn:
        conn.executescript(LEGACY_SCHEMA.read_text())
        conn.executemany("INSERT INTO users (id, name) VALUES (?, ?)", [(ALICE, "Alice"), (BOB, "Bob")])
        conn.execute(
            "INSERT INTO tasks (id, user_id, root_agent, status, finished_at)"
            " VALUES (?, ?, 'data', 'completed', '2026-09-24T08:00:01.000Z')",
            (LEGACY_TASK, ALICE),
        )
        conn.execute(
            "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, result_text)"
            " VALUES ('inv_legacy0001', ?, ?, 'data', 'user', 0, 'sales?', 'completed', 'done')",
            (LEGACY_TASK, ALICE),
        )
        conn.executemany(
            "INSERT INTO messages (user_id, agent, seq, task_id, invocation_id, role, sender, content, tool_calls_json,"
            " tool_call_id) VALUES (?, 'data', ?, ?, 'inv_legacy0001', ?, ?, ?, ?, ?)",
            [
                (ALICE, 1, LEGACY_TASK, "user", "user", "sales?", None, None),
                (ALICE, 2, LEGACY_TASK, "assistant", None, "", calls, None),
                (ALICE, 3, LEGACY_TASK, "tool", None, "rows", None, "c1"),
                (ALICE, 4, LEGACY_TASK, "assistant", None, "done", None, None),
            ],
        )
        conn.execute(
            "INSERT INTO datasets (id, user_id, invocation_id, name, source_sql, columns_json, rows_json, row_count)"
            " VALUES (?, ?, 'inv_legacy0001', 'sales', 'SELECT 1', ?, ?, 3)",
            (LEGACY_DATASET, ALICE, json.dumps([{"name": "n", "type": "INTEGER"}]), json.dumps([[0], [1], [2]])),
        )
        conn.execute("INSERT INTO memories (user_id, agent, kind, text) VALUES (?, 'data', 'fact', 'west revenue fell')", (ALICE,))
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
    db = await migrated_database(cfg.backend_db)
    seed_users(cfg.backend_db)
    bus, tokens = EventBus(), TokenRegistry()
    registry = registry_of(fake_agents)
    engine = Engine(cfg, db, bus, tokens, registry)
    await engine.recover()
    yield Harness(cfg, db, bus, tokens, registry, engine, fake_agents)
    await engine.stop()
    await db.dispose()
