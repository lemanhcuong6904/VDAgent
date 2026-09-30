"""The invocation engine: public API and the run task of every invocation.

Concurrency model (single process, single event loop):
- `Scheduler` keeps one `Stack` per (user, agent): the running invocation holds the stack lock,
  the others wait in FIFO order. Only the holder's run task writes that stack (stack lock).
- One asyncio run task per running invocation drives its turn: it starts the plugin's
  `agent.invoke(ctx)` as a separate task and handles the events `ctx` posts on the turn's inbox
  (`context.py`): contract checks (`contract.py`), persistence, SSE (`publisher.py`), agent calls
  (`calls.py`). A child's reply resolves the future its parent's `call_agent` awaits.
- Only the run task awaits DB writes for its run, and they are never interrupted: cancellation is
  cooperative. `cancel_task` flags the runs and cancels their in-flight invoke or compaction; each
  run then synthesises the missing tool results of its stack (stack integrity) before releasing it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine
from vdagent_sdk import AgentTimeoutError, ContractViolation, McpEndpoint, Peer

from vdagent_backend.config import Config
from vdagent_backend.conversations import Messages, Tasks
from vdagent_backend.core import EventBus, TokenRegistry, describe, new_id
from vdagent_backend.memory import ScopedMemory
from vdagent_backend.plugins import AgentRegistry
from vdagent_backend.runtime.calls import CallRouter
from vdagent_backend.runtime.compaction import COMPACT_TIMEOUT_S, compact
from vdagent_backend.runtime.context import Call, Emit, Ended, Event, ToolResult, TurnContext
from vdagent_backend.runtime.contract import check_call, check_emit, check_tool_result, final_answer
from vdagent_backend.runtime.history import missing_tool_results, to_message
from vdagent_backend.runtime.publisher import Publisher
from vdagent_backend.runtime.run import Cancelled, Run, Step
from vdagent_backend.runtime.scheduler import Scheduler

log = logging.getLogger(__name__)

RESTARTED = "backend restarted"
CANCELLED = "cancelled"
INVOKE_CANCEL_GRACE_S = 5.0  # how long a cancelled invoke may take to unwind before it is abandoned


class UnknownAgentError(Exception):
    """A message was posted to an agent that is not registered."""


class TaskNotFoundError(Exception):
    """No such task for this user."""


class TaskFinishedError(Exception):
    """The task already reached a terminal status."""


class IdempotencyConflictError(Exception):
    """An `Idempotency-Key` was reused by the same user and agent with different content (WS7 F-11)."""


# Startup recovery hook: called with (user_id, task_id) for every task the restart failed, e.g. to reconcile the
# task's artifacts (WS7 F-04). Wired by the composition root; the runtime itself does not know artifacts.
InterruptedHook = Callable[[str, str], Awaitable[Any]]


class _TurnFailed(Exception):
    """The plugin's `invoke` raised; `reason` is the invocation's failure reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _find_timeout(exc: BaseException) -> AgentTimeoutError | None:
    """The first `AgentTimeoutError` in `exc`, its exception groups, or its `__cause__` chain."""
    seen: set[int] = set()
    stack = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, AgentTimeoutError):
            return current
        if isinstance(current, BaseExceptionGroup):
            stack.extend(reversed(current.exceptions))  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        if current.__cause__ is not None:
            stack.append(current.__cause__)
    return None


class Engine:
    """Runs agent turns for posted messages and agent calls.

    Args:
        cfg: `max_depth`, `max_steps` and `mcp_public_url` are used.
        db: The Backend database.
        bus: SSE fan-out.
        tokens: Per-turn MCP tokens.
        registry: The loaded agents.
        compact_timeout_s: How long a stack compaction may take before the turn goes on without it.
        on_interrupted: Startup recovery hook, awaited per failed task (`InterruptedHook`); its errors are logged.
    """

    def __init__(
        self,
        cfg: Config,
        db: AsyncEngine,
        bus: EventBus,
        tokens: TokenRegistry,
        registry: AgentRegistry,
        *,
        compact_timeout_s: float = COMPACT_TIMEOUT_S,
        on_interrupted: InterruptedHook | None = None,
    ) -> None:
        self.registry = registry
        self._on_interrupted = on_interrupted
        self.compact_timeout_s = compact_timeout_s
        self._cfg = cfg
        self._db = db
        self._tokens = tokens
        self._tasks = Tasks(db)
        self._messages = Messages(db)
        self._publish = Publisher(bus)
        self._cancelled: set[str] = set()  # task ids cancelled while this process runs
        self._cancelling: dict[str, asyncio.Future[None]] = {}
        self._scheduler = Scheduler(self._publish, start=self._start, skip=lambda run: run.task_id in self._cancelled)
        self._calls = CallRouter(registry, cfg.max_depth, is_cancelled=lambda task_id: task_id in self._cancelled)

    # ------------------------------------------------------------------ lifecycle

    async def stop(self) -> None:
        """Abandon running invocations (the next startup's `recover` fails them)."""
        self._scheduler.stopping = True
        tasks = [run.task for run in self._scheduler.running() if run.task]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def recover(self) -> None:
        """Startup recovery: every queued/running invocation → failed (stack patched); every running task → failed with
        outcome `interrupted`, then `on_interrupted` for it. No automatic resume (WS7 F-04): the turn's MCP tokens and
        pending calls are gone; the user re-asks (optionally with the same Idempotency-Key)."""
        for row in await self._tasks.inflight_invocations():
            await self._patch_stack(row["user_id"], row["agent"], row["task_id"], row["id"], RESTARTED)
            await self._tasks.finish_invocation(row["id"], "failed", error=RESTARTED)
        for task in await self._tasks.fail_running_tasks():
            if self._on_interrupted is None:
                continue
            try:
                await self._on_interrupted(task["user_id"], task["id"])
            except Exception:  # never block startup on one task
                log.exception("startup recovery hook failed for task %s", task["id"])

    # ------------------------------------------------------------------ queries for the API

    def agent_status(self, user_id: str, agent: str) -> dict[str, Any]:
        """`{agent, busy, queue_len}` of stack (user, agent)."""
        return self._scheduler.status(user_id, agent)

    def agents(self, user_id: str) -> list[dict[str, Any]]:
        """Every registered agent with the user's stack status, in registration order."""
        out: list[dict[str, Any]] = []
        for entry in self.registry:
            status = self._scheduler.status(user_id, entry.name)
            out.append(
                {"name": entry.name, "description": entry.description, "busy": status["busy"], "queue_len": status["queue_len"]}
            )
        return out

    def pending(self, user_id: str, agent: str) -> list[dict[str, Any]]:
        """Queued inbound messages of stack (user, agent), in FIFO order."""
        return [
            {"invocation_id": r.id, "caller": r.caller, "inbound_text": r.inbound_text, "created_at": r.created_at}
            for r in self._scheduler.queued(user_id, agent)
        ]

    # ------------------------------------------------------------------ triggers

    async def post_message(
        self, user_id: str, agent: str, content: str, idempotency_key: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """A human message: a new task with a queued root invocation. Returns (task row, invocation row).

        With `idempotency_key` (WS7 F-11), a retry returns the task that key already started — its row gets
        `deduplicated = True` — instead of running again. Equal texts without a key are separate requests.

        Raises:
            UnknownAgentError: `agent` is not registered.
            IdempotencyConflictError: The key was used by this user and agent with different content.
        """
        if agent not in self.registry:
            raise UnknownAgentError(agent)
        if idempotency_key is not None:
            existing = await self._keyed(user_id, agent, content, idempotency_key)
            if existing is not None:
                return existing
            try:
                task, inv = await self._tasks.create_task(user_id, agent, content, idempotency_key)
            except IntegrityError:  # a concurrent retry with the same key won the insert
                existing = await self._keyed(user_id, agent, content, idempotency_key)
                if existing is None:
                    raise
                return existing
        else:
            task, inv = await self._tasks.create_task(user_id, agent, content)
        self._publish.task(task)
        self._publish.invocation(inv)
        run = Run(
            id=inv["id"],
            user_id=user_id,
            agent=agent,
            task_id=task["id"],
            caller="user",
            depth=0,
            inbound_text=content,
            created_at=inv["created_at"],
        )
        self._enqueue(run)
        return task, inv

    async def _keyed(
        self, user_id: str, agent: str, content: str, key: str
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        found = await self._tasks.find_keyed_task(user_id, agent, key)
        if found is None:
            return None
        task, inv = found
        if inv["inbound_text"] != content:
            raise IdempotencyConflictError(key)
        return {**task, "deduplicated": True}, inv

    async def cancel_task(self, user_id: str, task_id: str) -> dict[str, Any]:
        """Cancel a running task: drop its queued runs, stop its running ones, mark everything cancelled.

        Returns:
            The task row afterwards.

        Raises:
            TaskNotFoundError: No such task for this user.
            TaskFinishedError: The task had already finished.
        """
        task = await self._tasks.get_task(task_id, user_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        in_progress = self._cancelling.get(task_id)
        if in_progress is not None:
            await asyncio.shield(in_progress)
            return await self._task_row(task_id)
        if task["status"] != "running":
            raise TaskFinishedError(task_id)

        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._cancelling[task_id] = done
        self._cancelled.add(task_id)
        try:
            self._scheduler.drop_task(user_id, task_id)
            running = self._scheduler.running_of_task(user_id, task_id)
            for run in running:
                run.cancel_requested = True
                if run.rpc is not None:
                    run.rpc.cancel()
            await asyncio.gather(*(r.done.wait() for r in running))
            for row in await self._tasks.cancel_task_invocations(task_id):
                self._publish.invocation(row)
            row = await self._tasks.finish_task(task_id, "cancelled")
            if row is None:  # finished on its own while we were cancelling
                current = await self._task_row(task_id)
                if current["status"] != "cancelled":
                    raise TaskFinishedError(task_id)
                return current
            self._publish.task(row)
            return row
        finally:
            del self._cancelling[task_id]
            done.set_result(None)

    async def _task_row(self, task_id: str) -> dict[str, Any]:
        row = await self._tasks.get_task(task_id)
        assert row is not None
        return row

    # ------------------------------------------------------------------ scheduling

    def _enqueue(self, run: Run) -> None:
        if run.task_id in self._cancelled:
            return  # the cancel in progress marks its row cancelled
        self._scheduler.enqueue(run)

    def _start(self, run: Run) -> None:
        run.task = asyncio.create_task(self._run(run), name=f"invocation {run.id}")

    # ------------------------------------------------------------------ one invocation

    async def _run(self, run: Run) -> None:
        try:
            final, reason = await self._drive(run)
            self._settle(run)
            if run.cancel_requested:
                await self._patch_stack(run.user_id, run.agent, run.task_id, run.id, CANCELLED)
                row = await self._tasks.finish_invocation(run.id, "cancelled")
                if row is not None:
                    self._publish.invocation(row)
            elif reason is not None:
                await self._conclude_failed(run, reason)
            else:
                assert final is not None
                await self._conclude_completed(run, final)
        except asyncio.CancelledError:
            raise  # engine shutdown: startup recovery takes care of the rows
        except Exception:
            log.exception("invocation %s: bookkeeping failed", run.id)
        finally:
            self._settle(run)
            self._scheduler.release(run)
            run.done.set()

    async def _drive(self, run: Run) -> tuple[str | None, str | None]:
        """Prepare and run the turn. Returns (final content, None) or (None, failure reason)."""
        try:
            return await self._execute(run), None
        except Cancelled:
            return None, CANCELLED
        except asyncio.CancelledError:
            if run.cancel_requested:  # local cancel of the in-flight compaction
                return None, CANCELLED
            raise
        except ContractViolation as e:
            return None, f"contract violation: {e}"
        except _TurnFailed as e:
            return None, e.reason
        except Exception as e:
            log.exception("invocation %s crashed", run.id)
            return None, f"internal error: {e}"

    async def _execute(self, run: Run) -> str:
        entry = self.registry.get(run.agent)
        assert entry is not None  # runs exist only for registered agents; the registry is immutable
        row = await self._tasks.mark_invocation_running(run.id)
        self._publish.invocation(row)
        run.check_cancel()

        await compact(run, entry.agent, self._messages, self.compact_timeout_s)
        run.check_cancel()

        await self._append(run, role="user", sender=run.caller, content=run.inbound_text)
        token = run.token = self._tokens.issue(run.user_id, run.agent, run.id, run.task_id)
        summary = await self._messages.get_summary(run.user_id, run.agent)
        history = await self._messages.stack_history(run.user_id, run.agent)
        run.check_cancel()

        ctx = TurnContext(
            invocation_id=run.id,
            task_id=run.task_id,
            user_id=run.user_id,
            summary=summary or "",
            history=[to_message(m) for m in history],
            peers=[Peer(name=e.name, description=e.description) for e in self.registry if e.name != run.agent],
            mcp=McpEndpoint(url=self._cfg.mcp_public_url, token=token),
            memory=ScopedMemory(self._db, run.user_id, run.agent),
            max_steps=self._cfg.max_steps,
        )
        invoke = asyncio.create_task(entry.agent.invoke(ctx), name=f"invoke {run.agent} {run.id}")
        invoke.add_done_callback(lambda t: ctx.inbox.put_nowait(Ended(t)))
        run.rpc = invoke
        try:
            while True:
                final = await self._on_event(run, await ctx.inbox.get())
                if final is not None:
                    run.outcome = ctx.outcome
                    return final
                run.check_cancel()
        finally:
            ctx.close()
            await self._end_invoke(run, invoke)

    async def _end_invoke(self, run: Run, invoke: asyncio.Task[None]) -> None:
        """The turn is over: drop pending replies, then make sure the plugin's invoke task has ended."""
        run.rpc = None
        for future in run.step.replies.values():
            future.cancel()
        if not invoke.done():
            await asyncio.sleep(0)  # one tick: the plugin sees the ContractViolation set on the call it awaits
        if not invoke.done():
            invoke.cancel()
            done, _ = await asyncio.wait({invoke}, timeout=INVOKE_CANCEL_GRACE_S)
            if not done:
                log.warning("invocation %s: %s's invoke ignored cancellation; abandoning it", run.id, run.agent)
        if invoke.done() and not invoke.cancelled():
            invoke.exception()  # its outcome was handled or no longer matters; mark it retrieved

    async def _on_event(self, run: Run, event: Event) -> str | None:
        """Handle one `ctx` event; returns the final answer once `invoke` returned cleanly."""
        if isinstance(event, Ended):
            return self._on_ended(run, event.task)
        try:
            if isinstance(event, Emit):
                await self._on_emit(run, event)
            elif isinstance(event, ToolResult):
                await self._on_tool_result(run, event)
            else:
                await self._on_call(run, event)  # resolves or keeps its future
                return None
        except ContractViolation as violation:
            if not event.future.done():
                event.future.set_exception(violation)
            raise
        if not event.future.done():
            event.future.set_result(None)
        return None

    async def _on_emit(self, run: Run, event: Emit) -> None:
        check_emit(run.step, event.tool_calls)
        run.step = Step.emitted(event.content, event.tool_calls)
        calls = [{"id": tc.id, "name": tc.name, "arguments_json": tc.arguments_json} for tc in event.tool_calls]
        await self._append(run, role="assistant", content=event.content, tool_calls=calls or None)

    async def _on_tool_result(self, run: Run, event: ToolResult) -> None:
        check_tool_result(run.step, event.tool_call_id)
        run.step.resolve(event.tool_call_id)
        await self._append(run, role="tool", content=event.content, tool_call_id=event.tool_call_id)

    async def _on_call(self, run: Run, event: Call) -> None:
        tcid = event.tool_call_id
        check_call(run.step, tcid)
        run.step.record_call(tcid, event.future)

        target = event.target
        fields: dict[str, Any] = {
            "task_id": run.task_id,
            "user_id": run.user_id,
            "agent": target,
            "caller": run.agent,
            "parent_id": run.id,
            "tool_call_id": tcid,
            "depth": run.depth + 1,
            "inbound_text": event.message,
        }
        error = self._calls.rejection(run, target)
        if error is not None:
            row = await self._tasks.insert_invocation(id=new_id("inv"), status="rejected", error=error, **fields)
            self._publish.invocation(row)
            self._calls.reply(run, tcid, error)
            return

        child = Run(
            id=new_id("inv"),
            user_id=run.user_id,
            agent=target,
            task_id=run.task_id,
            caller=run.agent,
            depth=run.depth + 1,
            inbound_text=event.message,
            parent=run,
            tool_call_id=tcid,
        )
        self._calls.accept(run, child)  # same synchronous step as the checks (acyclic wait graph)
        try:
            row = await self._tasks.insert_invocation(id=child.id, status="queued", **fields)
        except BaseException:
            self._calls.drop(run, tcid)
            raise
        child.created_at = row["created_at"]
        self._publish.invocation(row)
        self._enqueue(child)

    def _on_ended(self, run: Run, task: asyncio.Task[None]) -> str:
        """`invoke` finished: map its exception, or check that it ended with an answer and return it."""
        run.check_cancel()
        if task.cancelled():
            raise _TurnFailed("INTERNAL: invoke was cancelled")
        error = task.exception()
        if error is not None:
            raise self._failure(run, error)
        return final_answer(run.step)

    @staticmethod
    def _failure(run: Run, error: BaseException) -> Exception:
        if isinstance(error, ContractViolation):
            return error
        timeout = _find_timeout(error)
        if timeout is not None:
            log.warning("invocation %s (%s): model timed out: %s", run.id, run.agent, timeout)
            return _TurnFailed(f"DEADLINE_EXCEEDED: {timeout}")
        log.error("invocation %s (%s): invoke raised", run.id, run.agent, exc_info=error)
        return _TurnFailed(f"INTERNAL: {describe(error)}")

    def _settle(self, run: Run) -> None:
        """The run left its turn: no more results, token revoked, outgoing edges removed."""
        self._calls.settle(run)
        self._tokens.revoke(run.token)
        run.token = None

    # ------------------------------------------------------------------ outcomes

    async def _conclude_completed(self, run: Run, final: str) -> None:
        row = await self._tasks.finish_invocation(run.id, "completed", result_text=final)
        if row is not None:
            self._publish.invocation(row)
        if run.parent is not None:
            self._calls.deliver(run, final)
        else:  # a root run reported `failed` fails its task (WS7 F-03); `partial` stays completed with its outcome
            await self._finish_task(run.task_id, "failed" if run.outcome == "failed" else "completed", run.outcome)

    async def _conclude_failed(self, run: Run, reason: str) -> None:
        log.warning("invocation %s (%s) failed: %s", run.id, run.agent, reason)
        await self._patch_stack(run.user_id, run.agent, run.task_id, run.id, reason)
        row = await self._tasks.finish_invocation(run.id, "failed", error=reason)
        if row is not None:
            self._publish.invocation(row)
        if run.parent is not None:
            self._calls.deliver(run, f"error: {run.agent} failed: {reason}")
        else:
            await self._finish_task(run.task_id, "failed")

    async def _finish_task(self, task_id: str, status: str, outcome: str | None = None) -> None:
        if task_id in self._cancelled:
            return  # the cancel owns the task's final status
        row = await self._tasks.finish_task(task_id, status, outcome)
        if row is not None:
            self._publish.task(row)

    async def _patch_stack(self, user_id: str, agent: str, task_id: str, invocation_id: str, reason: str) -> None:
        """Keep stack integrity for an invocation that wrote to its stack and did not finish its turn:
        synthesise the missing tool results, then `[turn failed: <reason>]`. No-op if it never started."""
        msgs = await self._messages.invocation_messages(invocation_id)
        if not msgs:
            return
        ids = dict(user_id=user_id, agent=agent, task_id=task_id, invocation_id=invocation_id)
        for tool_call_id in missing_tool_results(msgs):
            await self._append_message(
                **ids, role="tool", content=f"error: turn aborted ({reason})", tool_call_id=tool_call_id
            )
        await self._append_message(**ids, role="assistant", content=f"[turn failed: {reason}]")

    # ------------------------------------------------------------------ persistence + events

    async def _append(self, run: Run, **fields: Any) -> None:
        await self._append_message(
            user_id=run.user_id, agent=run.agent, task_id=run.task_id, invocation_id=run.id, **fields
        )

    async def _append_message(self, **fields: Any) -> None:
        self._publish.message(await self._messages.append_message(**fields))
