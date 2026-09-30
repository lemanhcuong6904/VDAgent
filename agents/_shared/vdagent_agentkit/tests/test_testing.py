from __future__ import annotations

import asyncio
import os
import time

import pytest

from vdagent_agentkit.testing import ContractContext, FakeMcp, assert_cancel_propagates, run_turn
from vdagent_sdk import SEND_TO_AGENT, ContractViolation, InvocationContext, ToolCall


class AskData:
    """A well-behaved agent: one send_to_agent to data, then a final answer."""

    async def invoke(self, ctx: InvocationContext) -> None:
        call = ToolCall("c1", SEND_TO_AGENT, '{"agent": "data", "message": "DOM?"}')
        await ctx.emit_assistant("", [call])
        reply = await ctx.call_agent("c1", "data", "DOM?")
        await ctx.emit_tool_result("c1", reply)
        await ctx.emit_assistant(f"Kết quả: {reply}")

    async def compact(self, previous_summary: str, messages: list[object]) -> str:
        return previous_summary


class Misbehaving(AskData):
    def __init__(self, fault: str) -> None:
        self.fault = fault

    async def invoke(self, ctx: InvocationContext) -> None:
        if self.fault == "result_first":
            await ctx.emit_tool_result("c1", "x")
        elif self.fault == "dangling":
            await ctx.emit_assistant("", [ToolCall("c1", "artifact_get", "{}")])
        elif self.fault == "environ":
            os.environ["VDAGENT_TEST_LEAK"] = "1"
            await ctx.emit_assistant("xong")
        elif self.fault == "blocking":
            time.sleep(0.3)
            await ctx.emit_assistant("xong")
        elif self.fault == "swallow":
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass
            await ctx.emit_assistant("xong")
        elif self.fault == "slow":
            await asyncio.sleep(10)


async def _data(message: str) -> str:
    return "61 ngày"


async def test_fake_ctx_records_emit_order() -> None:
    ctx = await run_turn(AskData(), ContractContext(agents={"data": _data}))
    assert [e[0] for e in ctx.events] == ["assistant", "call", "tool", "assistant"]
    assert ctx.final == "Kết quả: 61 ngày"
    assert ctx.agent_calls == [("data", "DOM?")]


@pytest.mark.parametrize("fault", ["result_first", "dangling"])
async def test_backend_rules_r2_to_r5_enforced(fault: str) -> None:
    with pytest.raises(ContractViolation):
        await run_turn(Misbehaving(fault), ContractContext())


async def test_r11_environ_write_detected() -> None:
    try:
        with pytest.raises(AssertionError, match="R11"):
            await run_turn(Misbehaving("environ"), ContractContext())
    finally:
        os.environ.pop("VDAGENT_TEST_LEAK", None)


async def test_r10_blocking_detected() -> None:
    with pytest.raises(AssertionError, match="R10"):
        await run_turn(Misbehaving("blocking"), ContractContext())


async def test_r9_cancel_checks() -> None:
    await assert_cancel_propagates(Misbehaving("slow"), ContractContext())
    with pytest.raises(AssertionError, match="R9"):
        await assert_cancel_propagates(Misbehaving("swallow"), ContractContext())


async def test_fake_mcp_json_and_errors() -> None:
    def fail(args: dict[str, object]) -> object:
        raise ValueError("artifact not found")

    mcp = FakeMcp({"get_user_context": lambda a: {"user_id": "u"}, "artifact_get": fail})
    async with mcp.factory("u", "t") as session:
        ok = await session.call_tool("get_user_context", {})
        bad = await session.call_tool("artifact_get", {"artifact_id": "x"})
    assert ok.text == '{"user_id": "u"}' and not ok.is_error
    assert bad.is_error and bad.text == "error: artifact not found"
    assert mcp.called("artifact_get") == [{"artifact_id": "x"}]
