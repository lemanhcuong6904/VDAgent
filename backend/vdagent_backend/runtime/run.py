"""In-memory state of queued and running invocations.

`Run` is one invocation, `Stack` one (user, agent) stack's lock holder and FIFO queue, and `Step`
the contract state of a run's latest assistant step (replaced as a whole on every emit).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from vdagent_sdk import ToolCall


class Cancelled(Exception):
    """Raised inside a run at a checkpoint once its task has been cancelled."""


@dataclass(eq=False)
class Step:
    """The latest assistant step of a turn, as the contract checks see it.

    Attributes:
        tool_calls: tool call id → tool name.
        unresolved: tool call ids without a tool result yet.
        called: tool call ids already passed to `call_agent`.
        replies: tool call id → the future its `call_agent` awaits.
        last_assistant: `(content, had tool calls)` of the step; None before the first emit.
    """

    tool_calls: dict[str, str] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)
    called: set[str] = field(default_factory=set)
    replies: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    last_assistant: tuple[str, bool] | None = None

    @classmethod
    def emitted(cls, content: str, tool_calls: Sequence[ToolCall]) -> Step:
        """The step `emit_assistant(content, tool_calls)` starts."""
        return cls(
            tool_calls={tc.id: tc.name for tc in tool_calls},
            unresolved={tc.id for tc in tool_calls},
            last_assistant=(content, bool(tool_calls)),
        )

    def resolve(self, tool_call_id: str) -> None:
        self.unresolved.discard(tool_call_id)

    def record_call(self, tool_call_id: str, reply: asyncio.Future[str]) -> None:
        self.called.add(tool_call_id)
        self.replies[tool_call_id] = reply


@dataclass(eq=False)
class Run:
    """One queued or running invocation."""

    id: str
    user_id: str
    agent: str
    task_id: str
    caller: str
    depth: int
    inbound_text: str
    created_at: str = ""
    parent: Run | None = None
    tool_call_id: str | None = None

    token: str | None = None
    rpc: asyncio.Task[Any] | None = None  # in-flight invoke or compaction, cancelled on task cancel
    task: asyncio.Task[None] | None = None
    cancel_requested: bool = False
    finished: bool = False  # left the turn; child results are discarded from here on
    outcome: str | None = None  # the business outcome its turn reported (`ctx.report_outcome`, WS7 F-03)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    step: Step = field(default_factory=Step)
    # accepted child calls awaiting their result: tool_call id → child run (one wait-for edge each)
    children: dict[str, Run] = field(default_factory=dict)

    def check_cancel(self) -> None:
        if self.cancel_requested:
            raise Cancelled


@dataclass(eq=False)
class Stack:
    """One (user, agent) stack: `running` holds the stack lock, `queue` waits in FIFO order."""

    running: Run | None = None
    queue: deque[Run] = field(default_factory=deque)
