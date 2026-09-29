"""The turn contract as pure checks over a `Step`: no database, no scheduling.

Each check raises `ContractViolation` with the text the plugin sees at its call and that becomes
the failure reason `contract violation: <text>`.
"""

from __future__ import annotations

from collections.abc import Sequence

from vdagent_sdk import SEND_TO_AGENT, ContractViolation, ToolCall

from vdagent_backend.runtime.run import Step


def check_emit(step: Step, tool_calls: Sequence[ToolCall]) -> None:
    """`emit_assistant`: the previous step is fully resolved and the new tool-call ids are valid."""
    if step.unresolved:
        raise ContractViolation(
            f"emit_assistant: tool calls {sorted(step.unresolved)} of the previous step have no result yet"
        )
    ids = [tc.id for tc in tool_calls]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ContractViolation(f"emit_assistant: tool-call ids must be non-empty and unique, got {ids}")


def check_tool_result(step: Step, tool_call_id: str) -> None:
    """`emit_tool_result`: answers an unresolved call of the step whose `call_agent` has returned."""
    what = f"emit_tool_result({tool_call_id!r})"
    reply = step.replies.get(tool_call_id)
    if reply is not None and not reply.done():
        raise ContractViolation(f"{what}: its call_agent is still waiting for the reply")
    if tool_call_id not in step.unresolved:
        raise ContractViolation(f"{what}: not an unresolved tool call of the latest assistant step")


def check_call(step: Step, tool_call_id: str) -> None:
    """`call_agent`: an unresolved, not yet called `send_to_agent` call of the step."""
    what = f"call_agent({tool_call_id!r})"
    name = step.tool_calls.get(tool_call_id)
    if name is None:
        raise ContractViolation(f"{what}: not a tool call of the latest assistant step")
    if name != SEND_TO_AGENT:
        raise ContractViolation(f"{what}: tool call is {name!r}, not {SEND_TO_AGENT}")
    if tool_call_id not in step.unresolved:
        raise ContractViolation(f"{what}: tool call already has a result")
    if tool_call_id in step.called:
        raise ContractViolation(f"{what}: already called once")


def final_answer(step: Step) -> str:
    """The turn's answer once `invoke` returned: the content of a last step without tool calls."""
    if step.unresolved:
        raise ContractViolation(f"invoke returned with unresolved tool calls {sorted(step.unresolved)}")
    if step.last_assistant is None or step.last_assistant[1]:
        raise ContractViolation("invoke returned without a final assistant step (one without tool calls)")
    return step.last_assistant[0]
