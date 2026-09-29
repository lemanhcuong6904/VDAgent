"""The turn contract, checked directly on `Step` values (no engine, no database)."""

from __future__ import annotations

import asyncio

import pytest
from vdagent_sdk import SEND_TO_AGENT, ContractViolation, ToolCall

from vdagent_backend.runtime.contract import check_call, check_emit, check_tool_result, final_answer
from vdagent_backend.runtime.run import Step


def _calls(*specs: tuple[str, str]) -> list[ToolCall]:
    return [ToolCall(tcid, name, "{}") for tcid, name in specs]


def _step(*specs: tuple[str, str], content: str = "") -> Step:
    return Step.emitted(content, _calls(*specs))


def _violation(check: object, *args: object) -> str:
    with pytest.raises(ContractViolation) as caught:
        check(*args)  # type: ignore[operator]
    return str(caught.value)


def test_emit_needs_every_previous_tool_call_resolved() -> None:
    step = _step(("q2", "run_query"), ("q1", "run_query"))
    step.resolve("q2")
    assert _violation(check_emit, step, []) == "emit_assistant: tool calls ['q1'] of the previous step have no result yet"


@pytest.mark.parametrize(("ids", "shown"), [(["x", "x"], "['x', 'x']"), ([""], "['']")], ids=["duplicate", "empty"])
def test_emit_needs_non_empty_unique_ids(ids: list[str], shown: str) -> None:
    calls = _calls(*((i, "t") for i in ids))
    assert _violation(check_emit, Step(), calls) == f"emit_assistant: tool-call ids must be non-empty and unique, got {shown}"


def test_tool_result_must_answer_an_unresolved_call_of_the_latest_step() -> None:
    step = _step(("q1", "run_query"))
    check_tool_result(step, "q1")
    step.resolve("q1")
    expected = "emit_tool_result('{}'): not an unresolved tool call of the latest assistant step"
    assert _violation(check_tool_result, step, "q1") == expected.format("q1")
    assert _violation(check_tool_result, step, "nope") == expected.format("nope")


async def test_tool_result_waits_for_a_pending_call_agent() -> None:
    step = _step(("c1", SEND_TO_AGENT))
    reply: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    step.record_call("c1", reply)
    assert _violation(check_tool_result, step, "c1") == "emit_tool_result('c1'): its call_agent is still waiting for the reply"
    reply.set_result("done")
    check_tool_result(step, "c1")


async def test_call_agent_checks_in_order() -> None:
    step = _step(("q1", "run_query"), ("c1", SEND_TO_AGENT), ("c2", SEND_TO_AGENT))
    assert _violation(check_call, step, "nope") == "call_agent('nope'): not a tool call of the latest assistant step"
    assert _violation(check_call, step, "q1") == "call_agent('q1'): tool call is 'run_query', not send_to_agent"
    check_call(step, "c1")
    step.record_call("c1", asyncio.get_running_loop().create_future())
    assert _violation(check_call, step, "c1") == "call_agent('c1'): already called once"
    step.resolve("c2")
    assert _violation(check_call, step, "c2") == "call_agent('c2'): tool call already has a result"


def test_final_answer_is_the_content_of_a_last_step_without_tool_calls() -> None:
    assert final_answer(_step(content="the answer")) == "the answer"
    no_final = "invoke returned without a final assistant step (one without tool calls)"
    assert _violation(final_answer, Step()) == no_final
    resolved = _step(("q1", "run_query"), content="looking")
    resolved.resolve("q1")
    assert _violation(final_answer, resolved) == no_final
    assert _violation(final_answer, _step(("q1", "run_query"))) == "invoke returned with unresolved tool calls ['q1']"
