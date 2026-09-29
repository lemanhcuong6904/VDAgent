"""Agent-to-agent calls: acceptance checks, the per-user wait-for graphs, and child results.

Synchronous: a call is checked and, when accepted, its wait-for edge is added in the same step,
so no other call can slip in between (the acyclic wait graph invariant).
"""

from __future__ import annotations

from collections.abc import Callable

from vdagent_backend.plugins import AgentRegistry
from vdagent_backend.runtime.run import Run
from vdagent_backend.runtime.waitgraph import WaitGraph


class CallRouter:
    """Routes `call_agent` between runs.

    Args:
        registry: The registered agents (call targets).
        max_depth: The deepest allowed invocation depth (the root is 0).
        is_cancelled: True for a task being cancelled; its results are discarded.
    """

    def __init__(self, registry: AgentRegistry, max_depth: int, is_cancelled: Callable[[str], bool]) -> None:
        self._registry = registry
        self._max_depth = max_depth
        self._is_cancelled = is_cancelled
        self._graphs: dict[str, WaitGraph] = {}

    def _graph(self, user_id: str) -> WaitGraph:
        return self._graphs.setdefault(user_id, WaitGraph())

    def rejection(self, run: Run, target: str) -> str | None:
        """The tool result that rejects `run`'s call to `target`, or None to accept it."""
        if target not in self._registry:
            return f"error: unknown agent '{target}'"
        if target == run.agent:
            return "error: you cannot call yourself"
        if run.depth + 1 > self._max_depth:
            return "error: call depth limit reached; answer your caller with what you have"
        if self._graph(run.user_id).has_path(target, run.agent):
            return f"error: calling {target} would deadlock (it is waiting on you); answer with what you have"
        return None

    def accept(self, run: Run, child: Run) -> None:
        """Record the accepted call `child` of `run` (one wait-for edge)."""
        assert child.tool_call_id is not None
        self._graph(run.user_id).add(run.agent, child.agent)
        run.children[child.tool_call_id] = child

    def drop(self, run: Run, tool_call_id: str) -> Run | None:
        """Forget an accepted call of `run` and its edge; the child run, if it was still pending."""
        child = run.children.pop(tool_call_id, None)
        if child is not None:
            self._graph(run.user_id).remove(run.agent, child.agent)
        return child

    def reply(self, run: Run, tool_call_id: str, content: str) -> None:
        """Resolve the `call_agent` that `run` awaits for `tool_call_id` (dropped once `run` left its turn)."""
        if run.finished or self._is_cancelled(run.task_id):
            return
        future = run.step.replies.get(tool_call_id)
        if future is not None and not future.done():
            future.set_result(content)

    def deliver(self, child: Run, content: str) -> None:
        """A child run finished: hand `content` to its parent, if the parent still waits for it."""
        parent = child.parent
        if parent is None or child.tool_call_id is None:
            return
        if parent.children.get(child.tool_call_id) is not child:
            return  # the parent already ended; its edges are gone
        self.drop(parent, child.tool_call_id)
        self.reply(parent, child.tool_call_id, content)

    def settle(self, run: Run) -> None:
        """`run` left its turn: no more results reach it and its outgoing edges are removed."""
        run.finished = True
        for tool_call_id in list(run.children):
            self.drop(run, tool_call_id)
