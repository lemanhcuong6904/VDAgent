"""Invocation engine (§4): scheduling, in-process agent turns, call checks, compaction,
failure / cancel / restart handling, and SSE publication.

Concurrency model (single process, single event loop):
- One `Stack` per (user, agent): `running` is the lock holder, `queue` the FIFO of waiting
  invocations (§4.2). Only the holder's asyncio task writes that stack's messages (I1).
- One asyncio task per running invocation (the *run task*) drives its turn: it starts the plugin's
  `agent.invoke(ctx)` as a separate task and handles the events `ctx` posts on the turn's inbox
  (`engine/context.py`): contract checks R2–R5, persistence, SSE, agent calls. A child's reply
  resolves the future its parent's `call_agent` awaits, set by whichever task finishes the child.
- The per-user `WaitGraph` gets edge `caller → target` synchronously with the call checks, so the
  graph stays acyclic (I3).
- Cancellation is cooperative: `cancel_task` flags the runs and cancels their in-flight invoke or
  compaction task; each run then patches its own stack (I2) before releasing it. DB writes run in
  the run task and are never interrupted.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.config import Config
from vdagent_backend.db import artifact_store, repo
from vdagent_backend.db.memory import ScopedMemory
from vdagent_backend.engine.context import Call, Emit, Ended, Event, ToolResult, TurnContext
from vdagent_backend.engine.waitgraph import WaitGraph
from vdagent_backend.ids import now_iso
from vdagent_contracts.envelope import ArtifactDraft, ArtifactStatus, Producer
from vdagent_backend.events import EventBus
from vdagent_backend.ids import new_id
from vdagent_backend.plugins import AgentRegistry
from vdagent_backend.tokens import TokenRegistry
from vdagent_sdk import SEND_TO_AGENT, AgentTimeoutError, ContractViolation, McpEndpoint, Message, Peer

log = logging.getLogger(__name__)

RESTARTED = "backend restarted"
CANCELLED = "cancelled"
COMPACT_TIMEOUT_S = 150.0  # plugin model timeout (120 s) plus margin
INVOKE_CANCEL_GRACE_S = 5.0  # how long a cancelled invoke may take to unwind before it is abandoned


class UnknownAgentError(Exception):
    pass


class IdempotencyConflictError(Exception):
    """An Idempotency-Key reused with different message content (WS7 F-11)."""


class TaskNotFoundError(Exception):
    pass


class TaskFinishedError(Exception):
    pass


class _TurnFailed(Exception):
    """The plugin's `invoke` raised; `reason` is the invocation's failure reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Cancelled(Exception):
    """Raised inside a run at a checkpoint once its task has been cancelled."""


@dataclass(eq=False)
class Run:
    """In-memory state of one queued or running invocation."""

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
    rpc: asyncio.Task[Any] | None = None  # in-flight invoke or compaction task, cancelled on task cancel
    task: asyncio.Task[None] | None = None
    cancel_requested: bool = False
    outcome: str | None = None  # WS7 F-03: run outcome reported through ctx.report_outcome
    finished: bool = False  # left the turn; child results are discarded from here on
    done: asyncio.Event = field(default_factory=asyncio.Event)

    # contract state (R2–R5) for the latest assistant step
    tool_calls: dict[str, str] = field(default_factory=dict)  # tool_call id → tool name
    unresolved: set[str] = field(default_factory=set)
    called: set[str] = field(default_factory=set)
    replies: dict[str, asyncio.Future[str]] = field(default_factory=dict)  # tool_call id → awaited reply
    last_assistant: tuple[str, bool] | None = None  # (content, had tool calls) of the latest step
    # accepted child calls awaiting their result: tool_call id → child run (one wait-for edge each)
    children: dict[str, Run] = field(default_factory=dict)

    def check_cancel(self) -> None:
        if self.cancel_requested:
            raise _Cancelled


@dataclass(eq=False)
class Stack:
    running: Run | None = None
    queue: deque[Run] = field(default_factory=deque)


def _to_message(row: Mapping[str, Any]) -> Message:
    """A stored message as OpenAI-shaped history; inbound messages are rendered `[from: <sender>] <text>`."""
    role = row["role"]
    if role == "user":
        return {"role": "user", "content": f"[from: {row['sender']}] {row['content']}"}
    if role == "assistant":
        calls = json.loads(row["tool_calls_json"]) if row["tool_calls_json"] else []
        if not calls:
            return {"role": "assistant", "content": row["content"]}
        return {
            "role": "assistant",
            "content": row["content"] or None,
            "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments_json"]}}
                for c in calls
            ],
        }
    return {"role": "tool", "tool_call_id": row["tool_call_id"] or "", "content": row["content"]}


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


def _describe(exc: BaseException) -> str:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:  # pyright: ignore[reportUnknownMemberType]
        exc = exc.exceptions[0]  # pyright: ignore[reportUnknownVariableType]
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class Engine:
    def __init__(
        self,
        cfg: Config,
        db: AsyncEngine,
        bus: EventBus,
        tokens: TokenRegistry,
        registry: AgentRegistry,
        *,
        compact_timeout_s: float = COMPACT_TIMEOUT_S,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.bus = bus
        self.tokens = tokens
        self.registry = registry
        self.compact_timeout_s = compact_timeout_s
        self._stacks: dict[tuple[str, str], Stack] = {}
        self._graphs: dict[str, WaitGraph] = {}
        self._cancelled: set[str] = set()  # task ids cancelled while this process runs
        self._cancelling: dict[str, asyncio.Future[None]] = {}
        self._stopping = False

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Startup recovery (§4.6)."""
        await self.recover()

    async def stop(self) -> None:
        """Abandon running invocations (startup recovery fails them next boot)."""
        self._stopping = True
        tasks = [s.running.task for s in self._stacks.values() if s.running is not None and s.running.task]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def recover(self) -> None:
        """§4.6: every queued/running invocation → failed (stack patched); every running task → failed."""
        for row in await repo.inflight_invocations(self.db):
            await self._patch_stack(row["user_id"], row["agent"], row["task_id"], row["id"], RESTARTED)
            await repo.finish_invocation(self.db, row["id"], "failed", error=RESTARTED)
        for task in await repo.fail_running_tasks(self.db):
            await self._reconcile_run_states(task["user_id"], task["id"])

    async def _reconcile_run_states(self, user_id: str, task_id: str) -> None:
        """WS7 F-04: a run_state still `running` after a restart gets a new `interrupted` version (history kept).

        No automatic resume: the interrupted turn's MCP tokens and pending calls are gone, so a resumed run would
        need a new task and re-validated inputs; the user re-asks (optionally with an Idempotency-Key).
        """
        for state in await artifact_store.list_artifacts(self.db, user_id, run_id=task_id, artifact_type="run_state"):
            if state.payload.get("status") not in ("running", "pending"):
                continue
            steps = [{**s, "status": "interrupted"} if s.get("status") in ("running", "pending") else s
                     for s in state.payload.get("steps", [])]
            draft = ArtifactDraft(
                artifact_id=state.artifact_id, artifact_type=state.artifact_type, schema_version=state.schema_version,
                status=ArtifactStatus.INVALID, producer=Producer(agent="backend", agent_version="recovery"),
                snapshot_refs=state.snapshot_refs, semantic_config_version=state.semantic_config_version,
                limitations=["INTERRUPTED:backend restarted"], reason_code="BACKEND_RESTARTED", reason="backend restarted during the run",
                payload={**state.payload, "status": "interrupted", "steps": steps,
                         "interrupted": {"reason": "backend restarted", "at": now_iso()}},
            )
            try:
                await artifact_store.put(self.db, user_id=user_id, run_id=task_id, task_id=task_id, draft=draft)
            except Exception:  # never block startup on one artifact
                log.exception("could not reconcile run_state %s of task %s", state.artifact_id, task_id)

    # ------------------------------------------------------------------ queries for the API

    def graph(self, user_id: str) -> WaitGraph:
        graph = self._graphs.get(user_id)
        if graph is None:
            graph = self._graphs[user_id] = WaitGraph()
        return graph

    def agent_status(self, user_id: str, agent: str) -> dict[str, Any]:
        stack = self._stacks.get((user_id, agent))
        return {
            "agent": agent,
            "busy": stack is not None and stack.running is not None,
            "queue_len": len(stack.queue) if stack is not None else 0,
        }

    def agents(self, user_id: str) -> list[dict[str, Any]]:
        out = []
        for entry in self.registry:
            status = self.agent_status(user_id, entry.name)
            out.append(
                {
                    "name": entry.name,
                    "description": entry.description,
                    "busy": status["busy"],
                    "queue_len": status["queue_len"],
                }
            )
        return out

    def pending(self, user_id: str, agent: str) -> list[dict[str, Any]]:
        """Queued inbound messages of stack (user, agent), in FIFO order."""
        stack = self._stacks.get((user_id, agent))
        if stack is None:
            return []
        return [
            {"invocation_id": r.id, "caller": r.caller, "inbound_text": r.inbound_text, "created_at": r.created_at}
            for r in stack.queue
        ]

    # ------------------------------------------------------------------ triggers

    async def post_message(
        self, user_id: str, agent: str, content: str, idempotency_key: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Human trigger (§4.1): new task + queued root invocation. Returns (task row, invocation row).

        WS7 F-11: with a client `idempotency_key`, a retry returns the task that key already started (the row gets
        `deduplicated = True`) instead of running again; the same key with other content raises
        `IdempotencyConflictError`. Equal texts without a key are separate requests and are never merged.
        """
        if agent not in self.registry:
            raise UnknownAgentError(agent)
        if idempotency_key is not None:
            existing = await self._keyed(user_id, agent, content, idempotency_key)
            if existing is not None:
                return existing
            try:
                task, inv = await repo.create_task(self.db, user_id, agent, content, idempotency_key)
            except IntegrityError:  # a concurrent retry with the same key won the insert
                existing = await self._keyed(user_id, agent, content, idempotency_key)
                if existing is None:
                    raise
                return existing
        else:
            task, inv = await repo.create_task(self.db, user_id, agent, content)
        self._publish_task(task)
        self._publish_invocation(inv)
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

    async def _keyed(self, user_id: str, agent: str, content: str, key: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        found = await repo.find_keyed_task(self.db, user_id, agent, key)
        if found is None:
            return None
        task, inv = found
        if inv["inbound_text"] != content:
            raise IdempotencyConflictError(key)
        return {**task, "deduplicated": True}, inv

    async def cancel_task(self, user_id: str, task_id: str) -> dict[str, Any]:
        """§4.6 cancel. Returns the task row afterwards."""
        task = await repo.get_task(self.db, task_id, user_id)
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
            for (uid, agent), stack in self._stacks.items():
                if uid == user_id and any(r.task_id == task_id for r in stack.queue):
                    stack.queue = deque(r for r in stack.queue if r.task_id != task_id)
                    self._publish_status(uid, agent)
            running = [
                s.running
                for (uid, _), s in self._stacks.items()
                if uid == user_id and s.running is not None and s.running.task_id == task_id
            ]
            for run in running:
                run.cancel_requested = True
                if run.rpc is not None:
                    run.rpc.cancel()
            await asyncio.gather(*(r.done.wait() for r in running))
            for row in await repo.cancel_task_invocations(self.db, task_id):
                self._publish_invocation(row)
            row = await repo.finish_task(self.db, task_id, "cancelled")
            if row is None:  # finished on its own while we were cancelling
                current = await self._task_row(task_id)
                if current["status"] != "cancelled":
                    raise TaskFinishedError(task_id)
                return current
            self._publish_task(row)
            return row
        finally:
            del self._cancelling[task_id]
            done.set_result(None)

    async def _task_row(self, task_id: str) -> dict[str, Any]:
        row = await repo.get_task(self.db, task_id)
        assert row is not None
        return row

    # ------------------------------------------------------------------ scheduling

    def _stack(self, user_id: str, agent: str) -> Stack:
        stack = self._stacks.get((user_id, agent))
        if stack is None:
            stack = self._stacks[(user_id, agent)] = Stack()
        return stack

    def _enqueue(self, run: Run) -> None:
        if run.task_id in self._cancelled:
            return  # the cancel in progress marks its row cancelled
        self._stack(run.user_id, run.agent).queue.append(run)
        self._pump(run.user_id, run.agent)

    def _pump(self, user_id: str, agent: str) -> None:
        stack = self._stack(user_id, agent)
        if self._stopping:
            return
        while stack.running is None and stack.queue:
            run = stack.queue.popleft()
            if run.task_id in self._cancelled:
                continue
            stack.running = run
            run.task = asyncio.create_task(self._run(run), name=f"invocation {run.id}")
        self._publish_status(user_id, agent)

    def _release(self, run: Run) -> None:
        stack = self._stack(run.user_id, run.agent)
        if stack.running is run:
            stack.running = None
        self._pump(run.user_id, run.agent)

    # ------------------------------------------------------------------ one invocation

    async def _run(self, run: Run) -> None:
        try:
            final, reason = await self._drive(run)
            self._settle(run)
            if run.cancel_requested:
                await self._patch_stack(run.user_id, run.agent, run.task_id, run.id, CANCELLED)
                row = await repo.finish_invocation(self.db, run.id, "cancelled")
                if row is not None:
                    self._publish_invocation(row)
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
            self._release(run)
            run.done.set()

    async def _drive(self, run: Run) -> tuple[str | None, str | None]:
        """Prepare and run the turn. Returns (final content, None) or (None, failure reason)."""
        try:
            return await self._execute(run), None
        except _Cancelled:
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
        row = await repo.mark_invocation_running(self.db, run.id)
        self._publish_invocation(row)
        run.check_cancel()

        await self._compact(run)
        run.check_cancel()

        await self._append(run, role="user", sender=run.caller, content=run.inbound_text)
        token = run.token = self.tokens.issue(run.user_id, run.agent, run.id, run.task_id)
        summary = await repo.get_summary(self.db, run.user_id, run.agent)
        history = await repo.stack_history(self.db, run.user_id, run.agent)
        run.check_cancel()

        entry = self.registry.get(run.agent)
        assert entry is not None  # runs exist only for registered agents; the registry is immutable
        ctx = TurnContext(
            invocation_id=run.id,
            task_id=run.task_id,
            user_id=run.user_id,
            summary=summary or "",
            history=[_to_message(m) for m in history],
            peers=[Peer(name=e.name, description=e.description) for e in self.registry if e.name != run.agent],
            mcp=McpEndpoint(url=self.cfg.mcp_public_url, token=token),
            memory=ScopedMemory(self.db, run.user_id, run.agent),
            max_steps=self.cfg.max_steps,
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
        for future in run.replies.values():
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
        if run.unresolved:
            raise ContractViolation(
                f"emit_assistant: tool calls {sorted(run.unresolved)} of the previous step have no result yet (R2)"
            )
        ids = [tc.id for tc in event.tool_calls]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ContractViolation(f"emit_assistant: tool-call ids must be non-empty and unique, got {ids} (R2)")
        run.tool_calls = {tc.id: tc.name for tc in event.tool_calls}
        run.unresolved = set(ids)
        run.called = set()
        run.replies = {}
        run.last_assistant = (event.content, bool(ids))
        calls = [{"id": tc.id, "name": tc.name, "arguments_json": tc.arguments_json} for tc in event.tool_calls]
        await self._append(run, role="assistant", content=event.content, tool_calls=calls or None)

    async def _on_tool_result(self, run: Run, event: ToolResult) -> None:
        tcid = event.tool_call_id
        what = f"emit_tool_result({tcid!r})"
        reply = run.replies.get(tcid)
        if reply is not None and not reply.done():
            raise ContractViolation(f"{what}: its call_agent is still waiting for the reply (R4)")
        if tcid not in run.unresolved:
            raise ContractViolation(f"{what}: not an unresolved tool call of the latest assistant step (R3)")
        run.unresolved.discard(tcid)
        await self._append(run, role="tool", content=event.content, tool_call_id=tcid)

    async def _on_call(self, run: Run, event: Call) -> None:
        tcid = event.tool_call_id
        what = f"call_agent({tcid!r})"
        name = run.tool_calls.get(tcid)
        if name is None:
            raise ContractViolation(f"{what}: not a tool call of the latest assistant step (R4)")
        if name != SEND_TO_AGENT:
            raise ContractViolation(f"{what}: tool call is {name!r}, not {SEND_TO_AGENT} (R4)")
        if tcid not in run.unresolved:
            raise ContractViolation(f"{what}: tool call already has a result (R4)")
        if tcid in run.called:
            raise ContractViolation(f"{what}: already called once (R4)")
        run.called.add(tcid)
        run.replies[tcid] = event.future

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
        error = self._call_error(run, target)
        if error is not None:
            row = await repo.insert_invocation(self.db, id=new_id("inv"), status="rejected", error=error, **fields)
            self._publish_invocation(row)
            self._send_result(run, tcid, error)
            return

        # Accept: the wait-for edge is added in the same synchronous step as the checks (I3).
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
        self.graph(run.user_id).add(run.agent, target)
        run.children[tcid] = child
        try:
            row = await repo.insert_invocation(self.db, id=child.id, status="queued", **fields)
        except BaseException:
            self._drop_call(run, tcid)
            raise
        child.created_at = row["created_at"]
        self._publish_invocation(row)
        self._enqueue(child)

    def _call_error(self, run: Run, target: str) -> str | None:
        """§4.4 checks in table order; the tool-error content, or None to accept."""
        if target not in self.registry:
            return f"error: unknown agent '{target}'"
        if target == run.agent:
            return "error: you cannot call yourself"
        if run.depth + 1 > self.cfg.max_depth:
            return "error: call depth limit reached; answer your caller with what you have"
        if self.graph(run.user_id).has_path(target, run.agent):
            return f"error: calling {target} would deadlock (it is waiting on you); answer with what you have"
        return None

    def _on_ended(self, run: Run, task: asyncio.Task[None]) -> str:
        """`invoke` finished: map its exception, or enforce R5 and return the final answer."""
        run.check_cancel()
        if task.cancelled():
            raise _TurnFailed("INTERNAL: invoke was cancelled")
        error = task.exception()
        if error is not None:
            raise self._failure(run, error)
        if run.unresolved:
            raise ContractViolation(f"invoke returned with unresolved tool calls {sorted(run.unresolved)} (R5)")
        if run.last_assistant is None or run.last_assistant[1]:
            raise ContractViolation("invoke returned without a final assistant step (one without tool calls) (R5)")
        return run.last_assistant[0]

    @staticmethod
    def _failure(run: Run, error: BaseException) -> Exception:
        if isinstance(error, ContractViolation):
            return error
        timeout = _find_timeout(error)
        if timeout is not None:
            log.warning("invocation %s (%s): model timed out: %s", run.id, run.agent, timeout)
            return _TurnFailed(f"DEADLINE_EXCEEDED: {timeout}")
        log.error("invocation %s (%s): invoke raised", run.id, run.agent, exc_info=error)
        return _TurnFailed(f"INTERNAL: {_describe(error)}")

    # ------------------------------------------------------------------ child results

    def _send_result(self, run: Run, tool_call_id: str, content: str) -> None:
        if run.finished or run.task_id in self._cancelled:
            return  # parent turn over / cancelled task: result discarded
        future = run.replies.get(tool_call_id)
        if future is not None and not future.done():
            future.set_result(content)

    def _drop_call(self, run: Run, tool_call_id: str) -> Run | None:
        child = run.children.pop(tool_call_id, None)
        if child is not None:
            self.graph(run.user_id).remove(run.agent, child.agent)
        return child

    def _deliver(self, child: Run, content: str) -> None:
        parent = child.parent
        if parent is None or child.tool_call_id is None:
            return
        if parent.children.get(child.tool_call_id) is not child:
            return  # parent already ended; its edges are gone
        self._drop_call(parent, child.tool_call_id)
        self._send_result(parent, child.tool_call_id, content)

    def _settle(self, run: Run) -> None:
        """The run left its stream: no more results, token revoked, outgoing edges removed."""
        run.finished = True
        self.tokens.revoke(run.token)
        run.token = None
        for tcid in list(run.children):
            self._drop_call(run, tcid)

    # ------------------------------------------------------------------ outcomes

    async def _conclude_completed(self, run: Run, final: str) -> None:
        row = await repo.finish_invocation(self.db, run.id, "completed", result_text=final)
        if row is not None:
            self._publish_invocation(row)
        if run.parent is not None:
            self._deliver(run, final)
        else:  # a root run reported `failed` fails its task (WS7 F-03); `partial` stays completed + outcome
            await self._finish_task(run.task_id, "failed" if run.outcome == "failed" else "completed", run.outcome)

    async def _conclude_failed(self, run: Run, reason: str) -> None:
        log.warning("invocation %s (%s) failed: %s", run.id, run.agent, reason)
        await self._patch_stack(run.user_id, run.agent, run.task_id, run.id, reason)
        row = await repo.finish_invocation(self.db, run.id, "failed", error=reason)
        if row is not None:
            self._publish_invocation(row)
        if run.parent is not None:
            self._deliver(run, f"error: {run.agent} failed: {reason}")
        else:
            await self._finish_task(run.task_id, "failed")

    async def _finish_task(self, task_id: str, status: str, outcome: str | None = None) -> None:
        if task_id in self._cancelled:
            return  # the cancel owns the task's final status
        row = await repo.finish_task(self.db, task_id, status, outcome)
        if row is not None:
            self._publish_task(row)

    async def _patch_stack(self, user_id: str, agent: str, task_id: str, invocation_id: str, reason: str) -> None:
        """§4.6 steps 1–2 for an invocation that wrote to its stack: synthesise the missing tool
        results (I2), then `[turn failed: <reason>]`. No-op for invocations that never started."""
        msgs = await repo.invocation_messages(self.db, invocation_id)
        if not msgs:
            return
        answered = {m["tool_call_id"] for m in msgs if m["role"] == "tool"}
        missing = [
            call["id"]
            for m in msgs
            if m["role"] == "assistant" and m["tool_calls_json"]
            for call in json.loads(m["tool_calls_json"])
            if call["id"] not in answered
        ]
        ids = dict(user_id=user_id, agent=agent, task_id=task_id, invocation_id=invocation_id)
        for tool_call_id in dict.fromkeys(missing):
            await self._append_message(
                **ids, role="tool", content=f"error: turn aborted ({reason})", tool_call_id=tool_call_id
            )
        await self._append_message(**ids, role="assistant", content=f"[turn failed: {reason}]")

    # ------------------------------------------------------------------ compaction

    async def _compact(self, run: Run) -> None:
        """§4.5: fold finished, other-task, uncompacted messages into the stack summary."""
        rows = await repo.compaction_candidates(self.db, run.user_id, run.agent, run.task_id)
        if not rows:
            return
        previous = await repo.get_summary(self.db, run.user_id, run.agent) or ""
        entry = self.registry.get(run.agent)
        assert entry is not None
        coro = asyncio.wait_for(entry.agent.compact(previous, [_to_message(r) for r in rows]), self.compact_timeout_s)
        compaction = asyncio.ensure_future(coro)
        run.rpc = compaction
        try:
            summary = await compaction
        except asyncio.CancelledError:
            raise
        except Exception as e:
            reason = f"no summary within {self.compact_timeout_s:g}s" if isinstance(e, TimeoutError) else _describe(e)
            log.warning("compaction of stack (%s, %s) failed, continuing: %s", run.user_id, run.agent, reason)
            return
        finally:
            run.rpc = None
        if not isinstance(summary, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            log.warning("compaction of stack (%s, %s) returned %s, not str; continuing", run.user_id, run.agent, type(summary).__name__)
            return
        await repo.apply_compaction(self.db, run.user_id, run.agent, summary, [r["id"] for r in rows])

    # ------------------------------------------------------------------ persistence + events

    async def _append(self, run: Run, **fields: Any) -> None:
        await self._append_message(
            user_id=run.user_id, agent=run.agent, task_id=run.task_id, invocation_id=run.id, **fields
        )

    async def _append_message(self, **fields: Any) -> None:
        row = await repo.append_message(self.db, **fields)
        self.bus.publish(row["user_id"], "message.appended", {"agent": row["agent"], "message": repo.message_dto(row)})

    def _publish_invocation(self, row: Mapping[str, Any]) -> None:
        self.bus.publish(row["user_id"], "invocation.updated", {"invocation": repo.invocation_dto(row)})

    def _publish_task(self, row: Mapping[str, Any]) -> None:
        self.bus.publish(row["user_id"], "task.updated", {"task": repo.task_dto(row)})

    def _publish_status(self, user_id: str, agent: str) -> None:
        self.bus.publish(user_id, "agent.status", self.agent_status(user_id, agent))
