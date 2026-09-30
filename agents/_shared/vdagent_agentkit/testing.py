"""Test helpers shared by every agent plugin (system prompt §4 rule 3): the SDK rules R2–R11 checked in one place.

`ContractContext` is an `InvocationContext` that enforces R2–R5 like the Backend does (raising `ContractViolation`)
and records every step. `run_turn` runs one turn and checks R5, R7, R10 and R11; `assert_cancel_propagates` checks
R9. `FakeMcp` is an in-memory MCP session; handlers return a dict (sent as JSON), a string, or a ToolOutcome.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from vdagent_sdk import SEND_TO_AGENT, Agent, ContractViolation, McpEndpoint, Message, Note, Peer, ToolCall

from vdagent_agentkit.mcp_client import McpSession, McpTool, ToolOutcome

PeerHandler = Callable[[str], Awaitable[str]]
MAX_LOOP_STALL_S = 0.2


@dataclass
class InMemoryMemory:
    """The Backend's per-(user, agent) notes, in memory: keyword search is a substring match."""

    notes: list[Note] = field(default_factory=list)
    _next_id: int = 1

    async def save(self, text: str, kind: str = "note", embedding: Sequence[float] | None = None) -> int:
        if not text or not kind:
            raise ValueError("text and kind must be non-empty")
        note = Note(id=self._next_id, kind=kind, text=text, created_at=f"{self._next_id:08d}")
        self._next_id += 1
        self.notes.append(note)
        return note.id

    async def search(self, query: str, limit: int = 5, embedding: Sequence[float] | None = None) -> list[Note]:
        return [n for n in reversed(self.notes) if query.lower() in n.text.lower()][:limit]

    async def recent(self, limit: int = 10) -> list[Note]:
        return list(reversed(self.notes))[:limit]

    async def delete(self, note_id: int) -> bool:
        before = len(self.notes)
        self.notes = [n for n in self.notes if n.id != note_id]
        return len(self.notes) < before


@dataclass
class ContractContext:
    """Enforces R2–R4 at each call and R5 in `finish()`; `agents` answer `call_agent` by target name."""

    inbound: str = "[from: user] xin chào"
    agents: dict[str, PeerHandler] = field(default_factory=dict)
    max_steps: int = 12
    summary: str = ""
    invocation_id: str = "inv_1"
    task_id: str = "t_1"
    user_id: str = "u_000000000001"
    mcp: McpEndpoint = McpEndpoint("http://mcp.test/mcp", "tok")
    events: list[tuple[str, Any, Any]] = field(default_factory=list)
    memory_store: InMemoryMemory | None = None  # None: the turn must not touch memory
    _open: dict[str, str] = field(default_factory=dict)  # tool_call_id → tool name, unresolved calls of the last step
    _pending_agent: set[str] = field(default_factory=set)
    _assistant_steps: int = 0
    _last_has_calls: bool = False
    _finished: bool = False

    @property
    def history(self) -> list[Message]:
        return [{"role": "user", "content": self.inbound}]

    @property
    def peers(self) -> list[Peer]:
        return [Peer(name=n, description=n) for n in self.agents]

    @property
    def memory(self) -> Any:
        if self.memory_store is None:
            raise ContractViolation("this test context provides no memory")
        return self.memory_store

    def _check_open(self) -> None:
        if self._finished:
            raise ContractViolation("R5: emitted after invoke returned")

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        self._check_open()
        if self._open:
            raise ContractViolation("R2: new assistant step while tool calls are unresolved")
        ids = [tc.id for tc in tool_calls]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ContractViolation("R2: tool-call ids must be non-empty and unique")
        self._assistant_steps += 1
        self._open = {tc.id: tc.name for tc in tool_calls}
        self._last_has_calls = bool(tool_calls)
        self.events.append(("assistant", content, [(tc.id, tc.name, tc.arguments_json) for tc in tool_calls]))

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        self._check_open()
        if tool_call_id not in self._open:
            raise ContractViolation(f"R3: no open tool call {tool_call_id!r}")
        if tool_call_id in self._pending_agent:
            raise ContractViolation("R4: result emitted while call_agent is pending")
        del self._open[tool_call_id]
        self.events.append(("tool", tool_call_id, content))

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        self._check_open()
        if self._open.get(tool_call_id) != SEND_TO_AGENT or tool_call_id in self._pending_agent:
            raise ContractViolation(f"R4: call_agent for {tool_call_id!r} is not an open send_to_agent call")
        handler = self.agents.get(target)
        if handler is None:
            raise ContractViolation(f"unknown agent {target!r}")
        self._pending_agent.add(tool_call_id)
        self.events.append(("call", target, message))
        try:
            return await handler(message)
        finally:
            self._pending_agent.discard(tool_call_id)

    def finish(self) -> None:
        if self._open:
            raise ContractViolation(f"R5: turn ended with unresolved tool calls {sorted(self._open)}")
        if self._assistant_steps == 0 or self._last_has_calls:
            raise ContractViolation("R5: the last assistant step must have no tool calls")
        self._finished = True

    @property
    def final(self) -> str:
        """Content of the last assistant step (the turn's answer)."""
        return next(e[1] for e in reversed(self.events) if e[0] == "assistant")

    @property
    def assistant_steps(self) -> int:
        return self._assistant_steps

    @property
    def agent_calls(self) -> list[tuple[str, str]]:
        return [(e[1], e[2]) for e in self.events if e[0] == "call"]


async def run_turn(agent: Agent, ctx: ContractContext, *, timeout_s: float = 10.0) -> ContractContext:
    """One turn with the SDK checks the Backend cannot enforce: R5, R7, R10 (loop never stalls), R11 (no environ writes)."""
    environ_before = dict(os.environ)
    stall = 0.0
    done = asyncio.Event()
    started = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal stall
        last = time.monotonic()
        started.set()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            stall = max(stall, now - last - 0.01)
            last = now

    beat = asyncio.create_task(heartbeat())
    await started.wait()
    try:
        async with asyncio.timeout(timeout_s):
            await agent.invoke(ctx)  # type: ignore[arg-type]
    finally:
        done.set()
        await beat
    ctx.finish()
    assert ctx.assistant_steps <= ctx.max_steps, f"R7: {ctx.assistant_steps} assistant steps > max_steps {ctx.max_steps}"
    assert stall < MAX_LOOP_STALL_S, f"R10: the event loop was blocked for {stall:.2f}s"
    assert dict(os.environ) == environ_before, "R11: the turn modified os.environ"
    return ctx


async def assert_cancel_propagates(agent: Agent, ctx: ContractContext, *, after_s: float = 0.05) -> None:
    """R9: cancelling a running turn raises CancelledError out of `invoke` (never swallowed)."""
    task = asyncio.create_task(agent.invoke(ctx))  # type: ignore[arg-type]
    await asyncio.sleep(after_s)
    assert not task.done(), "the turn finished before it could be cancelled; give it a slower dependency"
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    raise AssertionError("R9: invoke swallowed CancelledError")


Handler = Callable[[dict[str, Any]], Any]


@dataclass
class FakeMcp:
    """In-memory MCP session: `handlers[name](arguments)` → dict | str | ToolOutcome; raising ValueError = tool error."""

    handlers: dict[str, Handler] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def list_tools(self) -> list[McpTool]:
        return [McpTool(name=n, description=n, input_schema={"type": "object"}) for n in self.handlers]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        handler = self.handlers.get(name)
        if handler is None:
            return ToolOutcome(text=f"error: unknown tool '{name}'", is_error=True)
        try:
            out = handler(arguments)
            if isinstance(out, Awaitable):
                out = await out
        except ValueError as exc:
            return ToolOutcome(text=f"error: {exc}", is_error=True)
        if isinstance(out, ToolOutcome):
            return out
        return ToolOutcome(text=out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))

    @asynccontextmanager
    async def factory(self, url: str, token: str) -> AsyncIterator[McpSession]:
        yield self

    def called(self, name: str) -> list[dict[str, Any]]:
        return [args for n, args in self.calls if n == name]
