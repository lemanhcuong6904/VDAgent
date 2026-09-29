"""Invocation engine (main spec §4, plugins spec §5.3) with fake in-process agents."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable

import pytest

from conftest import ALICE, Harness, Session, wait_for
from vdagent_backend.db import repo
from vdagent_backend.engine import Engine, TaskFinishedError
from vdagent_sdk import AgentTimeoutError, ContractViolation, InvocationContext


def _roles(stack: list[dict]) -> list[tuple[str, str]]:
    return [(m["role"], m["content"]) for m in stack]


def _assert_i2(stack: list[dict]) -> None:
    """Every assistant tool call has exactly one tool result before the next assistant message."""
    open_calls: set[str] = set()
    for m in stack:
        if m["role"] == "assistant":
            assert not open_calls, f"unanswered tool calls {open_calls} before {m['content']!r}"
            open_calls = {c["id"] for c in json.loads(m["tool_calls_json"] or "[]")}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in open_calls, m
            open_calls.discard(m["tool_call_id"])
    assert not open_calls


async def _true(value: bool) -> bool:
    return value


async def _started(h: Harness, agent: str, n: int) -> bool:
    return len(h.agents[agent].starts) >= n


# --------------------------------------------------------------------------- happy path


async def test_delegation_round_trip_builds_both_stacks(harness: Harness) -> None:
    async def orchestrator(s: Session) -> None:
        reply = await s.ask("data", "revenue by region")
        await s.final(f"answer uses {reply}")

    async def data(s: Session) -> None:
        await s.final("dataset ds_000000000042")

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    task_id = await harness.post("orchestrator", "compare regions")
    await harness.wait_task(task_id, "completed")

    orch = await harness.stack("orchestrator")
    assert [(m["role"], m["sender"]) for m in orch] == [("user", "user"), ("assistant", None), ("tool", None), ("assistant", None)]
    assert orch[2]["content"] == "dataset ds_000000000042"
    assert orch[3]["content"] == "answer uses dataset ds_000000000042"
    data_stack = await harness.stack("data")
    assert (data_stack[0]["role"], data_stack[0]["sender"], data_stack[0]["content"]) == ("user", "orchestrator", "revenue by region")

    ctx = harness.agents["data"].starts[0]
    invs = {i["agent"]: i for i in await harness.invocations(task_id)}
    assert (ctx.invocation_id, ctx.task_id, ctx.user_id, ctx.max_steps) == (invs["data"]["id"], task_id, ALICE, 12)
    assert ctx.history == [{"role": "user", "content": "[from: orchestrator] revenue by region"}]
    assert sorted(p.name for p in ctx.peers) == ["compare", "insight", "orchestrator", "report"]
    assert {p.name: p.description for p in ctx.peers}["report"] == "report agent"
    assert ctx.mcp.url == harness.cfg.mcp_public_url and ctx.mcp.token
    assert harness.tokens.resolve(ctx.mcp.token) is None  # revoked once the turn ended

    assert invs["data"]["parent_id"] == invs["orchestrator"]["id"]
    assert invs["data"]["depth"] == 1 and invs["data"]["result_text"] == "dataset ds_000000000042"


async def test_history_is_openai_shaped_and_includes_earlier_turns_of_the_running_task(harness: Harness) -> None:
    async def orchestrator(s: Session) -> None:
        await s.ask("data", "one")
        await s.ask("data", "two")
        await s.final("ok")

    async def data(s: Session) -> None:
        if s.inbound.endswith("one"):
            await s.assistant(calls=[("q1", "run_query", {"sql": "SELECT 1"})])
            await s.tool("q1", "rows")
        await s.final("d")

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    task_id = await harness.post("orchestrator", "go")
    await harness.wait_task(task_id, "completed")

    assert harness.agents["data"].starts[1].history == [
        {"role": "user", "content": "[from: orchestrator] one"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "q1", "type": "function", "function": {"name": "run_query", "arguments": '{"sql": "SELECT 1"}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "q1", "content": "rows"},
        {"role": "assistant", "content": "d"},
        {"role": "user", "content": "[from: orchestrator] two"},
    ]


# --------------------------------------------------------------------------- scheduling


async def test_human_message_queues_behind_running_agent_call(harness: Harness) -> None:
    gate = asyncio.Event()

    async def orchestrator(s: Session) -> None:
        await s.ask("data", "first")
        await s.final("ok")

    async def data(s: Session) -> None:
        if "first" in s.inbound:
            await gate.wait()
        await s.final("done")

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    t1 = await harness.post("orchestrator", "go")
    await wait_for(lambda: _started(harness, "data", 1))
    t2 = await harness.post("data", "second")
    t3 = await harness.post("data", "third")

    pending = harness.engine.pending(ALICE, "data")
    assert [(p["caller"], p["inbound_text"]) for p in pending] == [("user", "second"), ("user", "third")]
    assert harness.engine.agent_status(ALICE, "data") == {"agent": "data", "busy": True, "queue_len": 2}
    await asyncio.sleep(0.1)
    assert len(harness.agents["data"].starts) == 1  # still blocked behind the running call

    gate.set()
    await harness.wait_task(t1, "completed")
    await harness.wait_task(t2, "completed")
    await harness.wait_task(t3, "completed")
    inbound = [(m["sender"], m["content"]) for m in await harness.stack("data") if m["role"] == "user"]
    assert inbound == [("orchestrator", "first"), ("user", "second"), ("user", "third")]


async def test_parallel_calls_to_different_targets_run_concurrently(harness: Harness) -> None:
    both_running = {"data": asyncio.Event(), "compare": asyncio.Event()}

    async def orchestrator(s: Session) -> None:
        calls = [s.send_to("data", "d"), s.send_to("compare", "c")]
        await s.assistant(calls=calls)
        replies = await asyncio.gather(*(s.call(tcid, a["agent"], a["message"]) for tcid, _, a in calls))
        for (tcid, _, _), reply in zip(calls, replies, strict=True):
            await s.tool(tcid, reply)
        await s.final("both")

    def worker(me: str, other: str) -> Callable[[Session], Awaitable[None]]:
        async def run(s: Session) -> None:
            both_running[me].set()
            await asyncio.wait_for(both_running[other].wait(), 2)  # deadlocks if serialised
            await s.final(f"{me} ok")

        return run

    harness.on("orchestrator", orchestrator)
    harness.on("data", worker("data", "compare"))
    harness.on("compare", worker("compare", "data"))
    task_id = await harness.post("orchestrator", "go")
    await harness.wait_task(task_id, "completed")
    tools = sorted(m["content"] for m in await harness.stack("orchestrator") if m["role"] == "tool")
    assert tools == ["compare ok", "data ok"]


# --------------------------------------------------------------------------- call checks


async def _rejection(harness: Harness, target: str) -> tuple[str, dict]:
    """Orchestrator → data; data then calls `target`. Returns data's reply and the call's row."""
    seen: list[str] = []

    async def orchestrator(s: Session) -> None:
        await s.ask("data", "work")
        await s.final("ok")

    async def data(s: Session) -> None:
        seen.append(await s.ask(target, "help"))
        await s.final("data done")

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    task_id = await harness.post("orchestrator", "go")
    await harness.wait_task(task_id, "completed")
    rows = [i for i in await harness.invocations(task_id) if i["caller"] == "data"]
    assert len(rows) == 1
    return seen[0], rows[0]


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ("nobody", "error: unknown agent 'nobody'"),
        ("data", "error: you cannot call yourself"),
        ("orchestrator", "error: calling orchestrator would deadlock (it is waiting on you); answer with what you have"),
    ],
    ids=["unknown", "self", "ancestor-cycle"],
)
async def test_call_rejections(harness: Harness, target: str, error: str) -> None:
    reply, row = await _rejection(harness, target)
    assert reply == error
    assert (row["status"], row["error"], row["agent"], row["depth"]) == ("rejected", error, target, 2)
    assert len(harness.agents["orchestrator"].starts) == 1


@pytest.mark.parametrize("cfg_overrides", [{"max_depth": 1}])
async def test_call_depth_limit(harness: Harness) -> None:
    reply, row = await _rejection(harness, "compare")
    assert reply == "error: call depth limit reached; answer your caller with what you have"
    assert row["status"] == "rejected"


async def test_cross_task_wait_for_cycle_is_rejected(harness: Harness) -> None:
    """§4.4 example: task 1 Orchestrator → Data → Compare while task 2 runs Compare → Data."""
    compare_gate = asyncio.Event()
    compare_results: list[str] = []

    async def orchestrator(s: Session) -> None:
        await s.ask("data", "task1 data")
        await s.final("t1 done")

    async def data(s: Session) -> None:
        reply = await s.ask("compare", "task1 compare")
        await s.final(f"data got {reply}")

    async def compare(s: Session) -> None:
        if "task2" in s.inbound:
            await compare_gate.wait()
            compare_results.append(await s.ask("data", "task2 needs data"))
        await s.final("compare done")

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    harness.on("compare", compare)

    t2 = await harness.post("compare", "task2 start")  # compare stack now held by task 2
    await wait_for(lambda: _started(harness, "compare", 1))
    t1 = await harness.post("orchestrator", "task1 start")

    async def data_waits_on_compare() -> bool:
        return any(i["caller"] == "data" and i["status"] == "queued" for i in await harness.invocations(t1))

    await wait_for(data_waits_on_compare)
    compare_gate.set()

    await harness.wait_task(t2, "completed")
    await harness.wait_task(t1, "completed")
    assert compare_results == ["error: calling data would deadlock (it is waiting on you); answer with what you have"]
    assert [i["status"] for i in await harness.invocations(t2) if i["caller"] == "compare"] == ["rejected"]


# --------------------------------------------------------------------------- contract (R2–R5)


async def _pending_tool_result(s: Session) -> None:
    tc = s.send_to("compare", "x")
    await s.assistant(calls=[tc])
    call = asyncio.ensure_future(s.call(tc[0], "compare", "x"))
    await asyncio.sleep(0)  # the call is posted first
    try:
        await s.tool(tc[0], "made up")
    finally:
        call.cancel()


async def _call_twice(s: Session) -> None:
    tc = s.send_to("compare", "x")
    await s.assistant(calls=[tc])
    await s.call(tc[0], "compare", "x")
    await s.call(tc[0], "compare", "x")


async def _double_result(s: Session) -> None:
    await s.assistant(calls=[("q1", "run_query", {})])
    await s.tool("q1", "rows")
    await s.tool("q1", "rows again")


async def _step_while_unresolved(s: Session) -> None:
    await s.assistant(calls=[("q1", "run_query", {})])
    await s.assistant("next")


async def _call_non_send_to_agent(s: Session) -> None:
    await s.assistant(calls=[("q1", "run_query", {})])
    await s.call("q1", "compare", "x")


@pytest.mark.parametrize(
    ("scenario", "detail"),
    [
        (_step_while_unresolved, "emit_assistant: tool calls ['q1'] of the previous step have no result yet (R2)"),
        (
            lambda s: s.assistant(calls=[("x", "t", {}), ("x", "t", {})]),
            "emit_assistant: tool-call ids must be non-empty and unique, got ['x', 'x'] (R2)",
        ),
        (lambda s: s.assistant(calls=[("", "t", {})]), "emit_assistant: tool-call ids must be non-empty and unique, got [''] (R2)"),
        (lambda s: s.tool("nope", "x"), "emit_tool_result('nope'): not an unresolved tool call of the latest assistant step (R3)"),
        (_double_result, "emit_tool_result('q1'): not an unresolved tool call of the latest assistant step (R3)"),
        (lambda s: s.call("nope", "compare", "x"), "call_agent('nope'): not a tool call of the latest assistant step (R4)"),
        (_call_non_send_to_agent, "call_agent('q1'): tool call is 'run_query', not send_to_agent (R4)"),
        (_call_twice, "_c1'): already called once (R4)"),
        (_pending_tool_result, "_c1'): its call_agent is still waiting for the reply (R4)"),
    ],
    ids=["R2-unresolved", "R2-duplicate-ids", "R2-empty-id", "R3-unknown", "R3-twice", "R4-unknown", "R4-not-send", "R4-twice", "R4-pending"],
)
async def test_contract_violations_raise_at_the_call_and_fail_the_turn_even_if_swallowed(
    harness: Harness, scenario: Callable[[Session], Awaitable[None]], detail: str
) -> None:
    caught: list[str] = []

    async def data(s: Session) -> None:
        try:
            await scenario(s)
        except ContractViolation as e:
            caught.append(str(e))
        # swallowed: the plugin returns as if nothing happened

    harness.on("data", data)
    task_id = await harness.post("data", "go")
    await harness.wait_task(task_id, "failed")
    (row,) = [i for i in await harness.invocations(task_id) if i["agent"] == "data"]
    assert len(caught) == 1 and caught[0].endswith(detail), caught
    assert (row["status"], row["error"]) == ("failed", f"contract violation: {caught[0]}")
    stack = await harness.stack("data")
    _assert_i2(stack)
    assert _roles(stack)[-1] == ("assistant", f"[turn failed: contract violation: {caught[0]}]")


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        (lambda s: asyncio.sleep(0), "contract violation: invoke returned without a final assistant step (one without tool calls) (R5)"),
        (lambda s: s.assistant(calls=[("q1", "run_query", {})]), "contract violation: invoke returned with unresolved tool calls ['q1'] (R5)"),
    ],
    ids=["no-step", "unresolved"],
)
async def test_returning_early_is_a_violation_and_the_parent_gets_an_error(
    harness: Harness, scenario: Callable[[Session], Awaitable[None]], error: str
) -> None:
    parent_results: list[str] = []

    async def orchestrator(s: Session) -> None:
        parent_results.append(await s.ask("data", "work"))
        await s.final("orchestrator survived")

    async def data(s: Session) -> None:
        await scenario(s)

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    task_id = await harness.post("orchestrator", "go")
    await harness.wait_task(task_id, "completed")

    row = next(i for i in await harness.invocations(task_id) if i["agent"] == "data")
    assert (row["status"], row["error"]) == ("failed", error)
    stack = await harness.stack("data")
    _assert_i2(stack)
    assert _roles(stack)[-1] == ("assistant", f"[turn failed: {error}]")
    assert parent_results == [f"error: data failed: {error}"]


async def test_a_step_with_resolved_tool_calls_is_not_a_final_answer(harness: Harness) -> None:
    async def data(s: Session) -> None:
        await s.assistant("looking", calls=[("q1", "run_query", {})])
        await s.tool("q1", "rows")

    harness.on("data", data)
    task_id = await harness.post("data", "go")
    await harness.wait_task(task_id, "failed")
    (row,) = await harness.invocations(task_id)
    assert row["error"] == "contract violation: invoke returned without a final assistant step (one without tool calls) (R5)"


async def test_ctx_is_closed_once_the_turn_ends(harness: Harness) -> None:
    kept: list[InvocationContext] = []

    async def data(s: Session) -> None:
        kept.append(s.ctx)
        await s.final("answer")

    harness.on("data", data)
    task_id = await harness.post("data", "go")
    await harness.wait_task(task_id, "completed")
    before = await harness.stack("data")
    (ctx,) = kept
    for late in (ctx.emit_assistant("late"), ctx.emit_tool_result("x", "late"), ctx.call_agent("x", "compare", "late")):
        with pytest.raises(ContractViolation, match="the turn is over"):
            await late
    assert await harness.stack("data") == before
    (row,) = await harness.invocations(task_id)
    assert (row["status"], row["result_text"]) == ("completed", "answer")


# --------------------------------------------------------------------------- plugin failures


def _chained_timeout() -> BaseException:
    try:
        raise AgentTimeoutError("model slow")
    except AgentTimeoutError as e:
        try:
            raise RuntimeError("step failed") from e
        except RuntimeError as outer:
            return outer


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AgentTimeoutError("LLM timed out"), "DEADLINE_EXCEEDED: LLM timed out"),
        (_chained_timeout(), "DEADLINE_EXCEEDED: model slow"),
        (ExceptionGroup("tools", [ValueError("x"), AgentTimeoutError("in group")]), "DEADLINE_EXCEEDED: in group"),
        (ValueError("kaput"), "INTERNAL: ValueError: kaput"),
    ],
    ids=["timeout", "chained-timeout", "grouped-timeout", "other"],
)
async def test_plugin_exceptions_fail_the_turn_patch_the_stack_and_answer_the_parent(
    harness: Harness, error: BaseException, reason: str
) -> None:
    parent_results: list[str] = []

    async def orchestrator(s: Session) -> None:
        parent_results.append(await s.ask("data", "work"))
        await s.final("handled")

    async def data(s: Session) -> None:
        await s.assistant(calls=[("q1", "run_query", {"sql": "SELECT 1"})])
        raise error

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    task_id = await harness.post("orchestrator", "go")
    await harness.wait_task(task_id, "completed")

    row = next(i for i in await harness.invocations(task_id) if i["agent"] == "data")
    assert (row["status"], row["error"]) == ("failed", reason)
    stack = await harness.stack("data")
    _assert_i2(stack)
    assert _roles(stack)[-2:] == [("tool", f"error: turn aborted ({reason})"), ("assistant", f"[turn failed: {reason}]")]
    assert parent_results == [f"error: data failed: {reason}"]


async def test_root_failure_fails_task(harness: Harness) -> None:
    async def orchestrator(s: Session) -> None:
        await s.call("nope", "data", "no such tool call")

    harness.on("orchestrator", orchestrator)
    task_id = await harness.post("orchestrator", "go")
    await harness.wait_task(task_id, "failed")
    (row,) = await harness.invocations(task_id)
    assert (row["status"], row["error"]) == (
        "failed",
        "contract violation: call_agent('nope'): not a tool call of the latest assistant step (R4)",
    )


# --------------------------------------------------------------------------- cancel


async def test_cancel_removes_queued_cancels_running_and_patches_stacks(harness: Harness) -> None:
    async def orchestrator(s: Session) -> None:
        calls = [s.send_to("data", "one"), s.send_to("data", "two")]  # same target → second is queued
        await s.assistant(calls=calls)
        await asyncio.gather(*(s.call(tcid, "data", args["message"]) for tcid, _, args in calls))
        await asyncio.Event().wait()

    async def data(s: Session) -> None:
        if s.inbound.endswith("after cancel"):
            await s.final("fresh")
            return
        await s.assistant(calls=[("q1", "run_query", {"sql": "SELECT 1"})])
        await asyncio.Event().wait()

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    task_id = await harness.post("orchestrator", "go")

    async def both_accepted() -> bool:
        stack = await harness.stack("data")
        return len(harness.engine.pending(ALICE, "data")) == 1 and any(m["role"] == "assistant" for m in stack)

    await wait_for(both_accepted)
    task = await harness.engine.cancel_task(ALICE, task_id)
    assert task["status"] == "cancelled"

    invs = await harness.invocations(task_id)
    assert {i["status"] for i in invs} == {"cancelled"}
    queued = next(i for i in invs if i["inbound_text"] == "two")
    assert queued["started_at"] is None
    assert harness.engine.pending(ALICE, "data") == []
    assert len(harness.agents["data"].starts) == 1
    root = next(i for i in invs if i["agent"] == "orchestrator")
    assert harness.agents["orchestrator"].cancelled == [root["id"]]

    for agent in ("orchestrator", "data"):
        stack = await harness.stack(agent)
        _assert_i2(stack)
        assert _roles(stack)[-1] == ("assistant", "[turn failed: cancelled]")
    assert [m["content"] for m in await harness.stack("orchestrator") if m["role"] == "tool"] == [
        "error: turn aborted (cancelled)"
    ] * 2

    # Locks were released: both stacks accept new work.
    t2 = await harness.post("data", "after cancel")
    await harness.wait_task(t2, "completed")
    with pytest.raises(TaskFinishedError):
        await harness.engine.cancel_task(ALICE, task_id)


async def test_cancel_during_a_turn_delivers_cancelled_error_into_invoke(harness: Harness) -> None:
    started = asyncio.Event()

    async def data(s: Session) -> None:
        await s.assistant("thinking")
        started.set()
        await asyncio.Event().wait()

    harness.on("data", data)
    task_id = await harness.post("data", "long job")
    await asyncio.wait_for(started.wait(), 5)
    assert (await harness.engine.cancel_task(ALICE, task_id))["status"] == "cancelled"

    (row,) = await harness.invocations(task_id)
    assert row["status"] == "cancelled"
    assert harness.agents["data"].cancelled == [row["id"]]
    assert _roles(await harness.stack("data"))[-1] == ("assistant", "[turn failed: cancelled]")


# --------------------------------------------------------------------------- restart


async def test_startup_recovery_fails_inflight_work_and_patches_stacks(harness: Harness) -> None:
    with sqlite3.connect(harness.cfg.backend_db) as conn:
        conn.execute("INSERT INTO tasks (id, user_id, root_agent, status) VALUES ('t_1', ?, 'orchestrator', 'running')", (ALICE,))
        conn.executemany(
            "INSERT INTO invocations (id, task_id, user_id, agent, caller, parent_id, depth, inbound_text, status)"
            " VALUES (?, 't_1', ?, ?, ?, ?, ?, ?, ?)",
            [
                ("inv_root", ALICE, "orchestrator", "user", None, 0, "go", "running"),
                ("inv_child", ALICE, "data", "orchestrator", "inv_root", 1, "work", "queued"),
            ],
        )
        conn.executemany(
            "INSERT INTO messages (user_id, agent, seq, task_id, invocation_id, role, sender, content, tool_calls_json)"
            " VALUES (?, 'orchestrator', ?, 't_1', 'inv_root', ?, ?, ?, ?)",
            [
                (ALICE, 1, "user", "user", "go", None),
                (ALICE, 2, "assistant", None, "", json.dumps([{"id": "c1", "name": "send_to_agent", "arguments_json": "{}"}])),
            ],
        )
    conn.close()

    await harness.engine.recover()

    assert (await repo.get_task(harness.db, "t_1"))["status"] == "failed"
    invs = {i["id"]: i for i in await harness.invocations("t_1")}
    assert {(i["status"], i["error"]) for i in invs.values()} == {("failed", "backend restarted")}
    stack = await harness.stack("orchestrator")
    _assert_i2(stack)
    assert _roles(stack)[2:] == [("tool", "error: turn aborted (backend restarted)"), ("assistant", "[turn failed: backend restarted]")]
    assert await harness.stack("data") == []  # the queued child never wrote to its stack


async def test_engine_restart_recovers_via_start(harness: Harness) -> None:
    """A second engine on the same DB (a BE restart) fails what the first left running."""
    gate = asyncio.Event()

    async def data(s: Session) -> None:
        await gate.wait()

    harness.on("data", data)
    task_id = await harness.post("data", "hang")
    await wait_for(lambda: _started(harness, "data", 1))
    await harness.engine.stop()

    engine2 = Engine(harness.cfg, harness.db, harness.bus, harness.tokens, harness.registry)
    await engine2.start()
    row = await repo.get_task(harness.db, task_id)
    assert row["status"] == "failed"
    gate.set()


# --------------------------------------------------------------------------- compaction


async def test_compaction_selects_only_finished_other_task_uncompacted_messages(harness: Harness) -> None:
    gate = asyncio.Event()

    async def orchestrator(s: Session) -> None:
        await s.ask("data", "task A data")
        await gate.wait()
        await s.final("A done")

    harness.on("orchestrator", orchestrator)
    t_c = await harness.post("data", "task C")  # finished before the others
    await harness.wait_task(t_c, "completed")
    t_a = await harness.post("orchestrator", "task A")  # stays running with messages on data's stack

    async def a_data_done() -> bool:
        return any(i["agent"] == "data" and i["status"] == "completed" for i in await harness.invocations(t_a))

    await wait_for(a_data_done)
    t_b = await harness.post("data", "task B")
    await harness.wait_task(t_b, "completed")

    fake = harness.agents["data"]
    assert fake.compacts == [
        (
            "",
            [
                {"role": "user", "content": "[from: user] task C"},
                {"role": "assistant", "content": "done: [from: user] task C"},
            ],
        )
    ]
    start_b = fake.starts[-1]
    assert start_b.summary == "SUMMARY#1"
    assert [m["content"] for m in start_b.history] == [
        "[from: orchestrator] task A data",
        "done: [from: orchestrator] task A data",
        "[from: user] task B",
    ]
    by_task: dict[str, set[bool]] = {}
    for m in await harness.stack("data"):
        by_task.setdefault(m["task_id"], set()).add(bool(m["compacted"]))
    assert by_task == {t_c: {True}, t_a: {False}, t_b: {False}}
    assert await repo.get_summary(harness.db, ALICE, "data") == "SUMMARY#1"

    gate.set()
    await harness.wait_task(t_a, "completed")


@pytest.mark.parametrize("mode", ["raise", "hang"])
async def test_compaction_failure_or_timeout_is_not_fatal(harness: Harness, mode: str) -> None:
    harness.engine.compact_timeout_s = 0.1
    t1 = await harness.post("data", "first")
    await harness.wait_task(t1, "completed")
    harness.agents["data"].compact_mode = mode  # type: ignore[assignment]
    t2 = await harness.post("data", "second")
    await harness.wait_task(t2, "completed")

    fake = harness.agents["data"]
    assert len(fake.compacts) == 1
    start = fake.starts[-1]
    assert start.summary == ""
    assert [m["content"] for m in start.history] == ["[from: user] first", "done: [from: user] first", "[from: user] second"]
    assert not any(m["compacted"] for m in await harness.stack("data"))


async def test_cancel_abandons_an_in_flight_compaction(harness: Harness) -> None:
    t1 = await harness.post("data", "first")
    await harness.wait_task(t1, "completed")
    harness.agents["data"].compact_mode = "hang"
    t2 = await harness.post("data", "second")
    await wait_for(lambda: _true(len(harness.agents["data"].compacts) == 1))
    assert (await harness.engine.cancel_task(ALICE, t2))["status"] == "cancelled"
    assert len(harness.agents["data"].starts) == 1


# --------------------------------------------------------------------------- events


async def test_events_are_published_for_the_owning_user(harness: Harness) -> None:
    alice, bob = harness.bus.subscribe(ALICE), harness.bus.subscribe("u_000000000002")
    task_id = await harness.post("data", "hello")
    await harness.wait_task(task_id, "completed")

    names = []
    while not alice.queue.empty():
        ev = await alice.next()
        names.append(ev.event)
    assert {"task.updated", "invocation.updated", "message.appended", "agent.status"} <= set(names)
    assert bob.queue.empty()


async def test_ctx_memory_is_scoped_to_the_invoked_agent_and_user_and_outlives_the_task(harness: Harness) -> None:
    seen: list[list[str]] = []

    async def orchestrator(s: Session) -> None:
        await s.ask("data", "remember something")
        await s.final("ok")

    async def data(s: Session) -> None:
        seen.append([n.text for n in await s.ctx.memory.recent()])
        await s.ctx.memory.save(f"{s.ctx.user_id} asked: {s.inbound}", "fact")
        await s.final("saved")

    harness.on("orchestrator", orchestrator)
    harness.on("data", data)
    await harness.wait_task(await harness.post("orchestrator", "go"), "completed")
    await harness.wait_task(await harness.post("data", "again"), "completed")
    await harness.wait_task(await harness.post("data", "as bob", user_id="u_000000000002"), "completed")

    assert seen == [[], [f"{ALICE} asked: [from: orchestrator] remember something"], []]
    assert await harness.agents["orchestrator"].starts[0].memory.recent() == []


async def test_agent_list_comes_from_the_registry_without_health(harness: Harness) -> None:
    agents = harness.engine.agents(ALICE)
    assert [a["name"] for a in agents] == ["orchestrator", "data", "compare", "insight", "report"]
    assert agents[1] == {"name": "data", "description": "data agent", "busy": False, "queue_len": 0}
