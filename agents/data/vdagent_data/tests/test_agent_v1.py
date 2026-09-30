"""The Data agent as the Backend runs it: a contract-v1.0 message in the chat is answered in the SDK's steps.

The narration of the work comes first, as for a `StepSpec@1` turn; the last step is the answer, a short closing line and
exactly one ```json fence holding the contract's reply (REPORT or COMMAND_ACK). The older `StepSpec@1` message is unchanged.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from vdagent_data.agent import DataAgent, build_agent
from vdagent_data.contract_v1 import CommandAck, ReportMessage, parse_message
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_data.tests.test_agent_narration import agent, turn
from vdagent_data.tests.test_agent_steps import Ctx as BaseCtx
from vdagent_data.tests.test_agent_steps import factory
from vdagent_data.tests.test_wire import EXAMPLES, dispatch, ent

FENCE = re.compile(r"```json\n(.*?)\n```", re.S)


def reply_of(ctx: Any) -> tuple[str, dict[str, Any]]:
    content, calls = ctx.steps[-1]
    assert calls == [] and content.count("```json") == 1 and not content.strip().startswith("```")
    [raw] = FENCE.findall(content)
    return content, json.loads(raw)


async def test_a_dispatch_is_narrated_and_then_answered_with_the_contracts_report(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, json.dumps(dispatch({"entities": [ent("A12-08", "UNIT")]}, question="Vì sao căn A12-08 bán chậm?")))
    assert 4 <= len(ctx.steps) <= 12 and all(text.strip() for text, _ in ctx.steps)
    assert any(calls for _, calls in ctx.steps[:-1])  # the real reads and writes of the turn are shown
    content, raw = reply_of(ctx)
    message = parse_message(raw)
    assert isinstance(message, ReportMessage) and message.body.kind == "DONE" and message.body.result is not None
    assert content.split("```json")[0].strip()  # a natural-language closing precedes the JSON


async def test_a_message_that_is_not_valid_gets_an_ack_and_no_narration(mcp_tools: McpTools) -> None:
    bad = dispatch({"entities": [ent("A12-08", "UNIT")]})
    bad["body"].pop("objective")
    ctx = await turn(mcp_tools, json.dumps(bad))
    assert len(ctx.steps) == 1
    _, raw = reply_of(ctx)
    ack = CommandAck.model_validate(raw)
    assert ack.ack_status == "REJECTED" and ack.reject is not None and ack.reject.code == "MALFORMED_MESSAGE"


async def test_the_question_and_its_answer_work_across_two_turns_of_the_same_agent(mcp_tools: McpTools) -> None:
    data: DataAgent = agent(mcp_tools)
    first = BaseCtx(json.dumps(dispatch()))
    await data.invoke(first)
    _, raw = reply_of(first)
    question = parse_message(raw).body.question  # type: ignore[union-attr]
    assert question is not None and question.reason_code == "AMBIGUOUS_REQUEST"
    answer = copy.deepcopy(EXAMPLES["E11"])
    answer["body"].update(question_id=question.question_id, selected_option_ids=[question.options[0].option_id], answered_by="u")
    second = BaseCtx(json.dumps(answer))
    await data.invoke(second)
    _, raw = reply_of(second)
    assert parse_message(raw).body.kind == "DONE"  # type: ignore[union-attr]


async def test_the_older_stepspec_message_is_still_answered_as_before(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools)
    content, _ = ctx.steps[-1]
    assert "AgentReport@1" in content and "message_type" not in content


def test_the_warehouse_profile_comes_from_the_environment() -> None:
    assert build_agent({"DATA_LLM": "off"}).profile == "mock"  # type: ignore[attr-defined]
    assert build_agent({"DATA_LLM": "off", "DATA_DW_PROFILE": "real"}).profile == "real"  # type: ignore[attr-defined]


async def test_the_real_profile_reaches_the_steps(mcp_tools: McpTools) -> None:
    data = DataAgent(llm=None, mcp_session_factory=factory(mcp_tools), system_prompt="x", compact_prompt="y", profile="real")
    ctx = BaseCtx(json.dumps(dispatch({"entities": [ent("A12-08", "UNIT")]})))
    await data.invoke(ctx)
    _, raw = reply_of(ctx)
    codes = {w.details["raw"] for w in parse_message(raw).body.result.warnings}  # type: ignore[union-attr]
    assert "SNAPSHOT_STATUS_ASSUMED" in codes and "SYNTHETIC_SOURCE:net_area_m2" not in codes


async def test_a_question_is_narrated_as_a_question_and_not_as_a_failure(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, json.dumps(dispatch()))
    content, _ = ctx.steps[-1]
    closing = content.split("```json")[0]
    assert "chọn" in closing and "Không hoàn thành" not in closing and "INPUT_REQUIRED" not in closing
    assert "Landmark" in closing  # says what it asks about
