"""Stack scheduling (the stack lock invariant): one running invocation per (user, agent).

Synchronous: every method runs to completion without awaiting, so the queue and the lock holder
never change under a caller. Stacks are indexed per user, so a user's operations touch only that
user's stacks.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from vdagent_backend.runtime.publisher import Publisher
from vdagent_backend.runtime.run import Run, Stack


class Scheduler:
    """Queues runs per stack and starts the next one whenever a stack's lock is free.

    Args:
        publisher: Receives `agent.status` after every change of a stack.
        start: Starts a run that just took its stack's lock (creates its run task).
        skip: True for a queued run that must be dropped instead of started (cancelled task).
    """

    def __init__(self, publisher: Publisher, start: Callable[[Run], None], skip: Callable[[Run], bool]) -> None:
        self._publish = publisher
        self._start = start
        self._skip = skip
        self._stacks: dict[str, dict[str, Stack]] = {}
        self.stopping = False

    def _stack(self, user_id: str, agent: str) -> Stack:
        return self._stacks.setdefault(user_id, {}).setdefault(agent, Stack())

    def enqueue(self, run: Run) -> None:
        self._stack(run.user_id, run.agent).queue.append(run)
        self.pump(run.user_id, run.agent)

    def pump(self, user_id: str, agent: str) -> None:
        """Start queued runs while the stack is free (not once stopping)."""
        stack = self._stack(user_id, agent)
        if self.stopping:
            return
        while stack.running is None and stack.queue:
            run = stack.queue.popleft()
            if self._skip(run):
                continue
            stack.running = run
            self._start(run)
        self._publish.status(user_id, self.status(user_id, agent))

    def release(self, run: Run) -> None:
        """`run` left its stack: free the lock and start the next run."""
        stack = self._stack(run.user_id, run.agent)
        if stack.running is run:
            stack.running = None
        self.pump(run.user_id, run.agent)

    def drop_task(self, user_id: str, task_id: str) -> None:
        """Remove the task's queued runs from the user's stacks."""
        for agent, stack in self._stacks.get(user_id, {}).items():
            if any(r.task_id == task_id for r in stack.queue):
                stack.queue = deque(r for r in stack.queue if r.task_id != task_id)
                self._publish.status(user_id, self.status(user_id, agent))

    def running_of_task(self, user_id: str, task_id: str) -> list[Run]:
        """The task's runs that hold a stack lock."""
        stacks = self._stacks.get(user_id, {}).values()
        return [s.running for s in stacks if s.running is not None and s.running.task_id == task_id]

    def running(self) -> list[Run]:
        """Every run that holds a stack lock, of every user."""
        return [s.running for user in self._stacks.values() for s in user.values() if s.running is not None]

    def queued(self, user_id: str, agent: str) -> list[Run]:
        """The stack's waiting runs in FIFO order."""
        stack = self._stacks.get(user_id, {}).get(agent)
        return list(stack.queue) if stack is not None else []

    def status(self, user_id: str, agent: str) -> dict[str, Any]:
        """`{agent, busy, queue_len}` of stack (user, agent)."""
        stack = self._stacks.get(user_id, {}).get(agent)
        return {
            "agent": agent,
            "busy": stack is not None and stack.running is not None,
            "queue_len": len(stack.queue) if stack is not None else 0,
        }
