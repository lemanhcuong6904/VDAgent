"""The in-process `InvocationContext` (plugins spec §5.3) and the events it posts to its run.

`TurnContext` never touches the DB or the engine's state: each method posts one event on the run's
inbox and awaits the event's future. The run task (the stack lock holder, I1) checks the contract
(R2–R5), persists and publishes, then resolves the future, or sets `ContractViolation` on it and
fails the turn. Cancelling the plugin's task therefore never interrupts a DB write.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from vdagent_sdk import ContractViolation, McpEndpoint, Memory, Message, Peer, ToolCall


@dataclass(frozen=True, eq=False)
class Emit:
    content: str
    tool_calls: tuple[ToolCall, ...]
    future: asyncio.Future[None]


@dataclass(frozen=True, eq=False)
class ToolResult:
    tool_call_id: str
    content: str
    future: asyncio.Future[None]


@dataclass(frozen=True, eq=False)
class Call:
    tool_call_id: str
    target: str
    message: str
    future: asyncio.Future[str]


@dataclass(frozen=True, eq=False)
class Ended:
    """Posted by the invoke task's done-callback."""

    task: asyncio.Task[None]


Event = Emit | ToolResult | Call | Ended


RUN_OUTCOMES = frozenset({"completed", "partial", "failed"})


class TurnContext:
    def __init__(
        self,
        *,
        invocation_id: str,
        task_id: str,
        user_id: str,
        summary: str,
        history: list[Message],
        peers: list[Peer],
        mcp: McpEndpoint,
        memory: Memory,
        max_steps: int,
    ) -> None:
        self.invocation_id = invocation_id
        self.task_id = task_id
        self.user_id = user_id
        self.summary = summary
        self.history = history
        self.peers = peers
        self.mcp = mcp
        self.memory = memory  # direct DB access: not a transcript event, outside R2–R5
        self.max_steps = max_steps
        self.inbox: asyncio.Queue[Event] = asyncio.Queue()
        self._closed = False
        self.outcome: str | None = None  # WS7 F-03: run outcome reported by the plugin

    def report_outcome(self, outcome: str) -> None:
        """Report the business outcome of this turn's run: completed | partial | failed (WS7 F-03).

        A root run reported `failed` ends its task as `failed`; `partial` stays `completed` with outcome `partial`.
        """
        if self._closed:
            raise ContractViolation("report_outcome: the turn is over")
        if outcome not in RUN_OUTCOMES:
            raise ContractViolation(f"report_outcome: unknown outcome {outcome!r}; use one of {sorted(RUN_OUTCOMES)}")
        self.outcome = outcome

    def close(self) -> None:
        """End the turn: later calls raise; events still queued get `ContractViolation`."""
        self._closed = True
        while not self.inbox.empty():
            event = self.inbox.get_nowait()
            if not isinstance(event, Ended) and not event.future.done():
                event.future.set_exception(ContractViolation(f"{_what(event)}: the turn is over"))

    def _post(self, what: str, make: Callable[[asyncio.Future[Any]], Event]) -> asyncio.Future[Any]:
        if self._closed:
            raise ContractViolation(f"{what}: the turn is over")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.inbox.put_nowait(make(future))
        return future

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        await self._post("emit_assistant", lambda f: Emit(content, tuple(tool_calls), f))

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        await self._post(f"emit_tool_result({tool_call_id!r})", lambda f: ToolResult(tool_call_id, content, f))

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        return await self._post(f"call_agent({tool_call_id!r})", lambda f: Call(tool_call_id, target, message, f))


def _what(event: Emit | ToolResult | Call) -> str:
    if isinstance(event, Emit):
        return "emit_assistant"
    if isinstance(event, ToolResult):
        return f"emit_tool_result({event.tool_call_id!r})"
    return f"call_agent({event.tool_call_id!r})"
