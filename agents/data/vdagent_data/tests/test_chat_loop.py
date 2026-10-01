"""The explanation chat's LLM loop: tools in, a checked answer out. The LLM is a script; the data is the real mock DW.

What the loop guarantees, whatever the model says: the answer holds no number or identifier that no tool returned (it is asked
once to rewrite, then replaced by a plain refusal), the loop ends after a fixed number of rounds, and nothing in it writes.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from vdagent_sdk import ToolCall

from vdagent_data.chat.loop import (
    MAX_ROUNDS,
    NO_PACKAGES_TEXT,
    STEP_LIMIT_TEXT,
    TIMEOUT_TEXT,
    UNGROUNDED_TEXT,
    ChatLoop,
    chat_turns,
)
from vdagent_data.llm import AssistantMessage, LLMTimeoutError
from vdagent_data.tests.conftest import McpPort
from vdagent_data.tests.test_chat_tools import UNIT_ROW, fetched
from vdagent_data.tests.test_v1_steps import ent, truth

QUESTION = [{"role": "user", "content": "[from: user] Căn A12-08 đã tồn bao lâu?"}]


class ScriptedLLM:
    def __init__(self, *replies: AssistantMessage | Exception) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str) -> AssistantMessage:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "tool_choice": tool_choice})
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class Sink:
    def __init__(self) -> None:
        self.steps: list[tuple[str, list[tuple[ToolCall, str]]]] = []

    async def step(self, text: str, calls: list[tuple[ToolCall, str]]) -> None:
        self.steps.append((text, calls))


def ask(name: str, **args: Any) -> AssistantMessage:
    return AssistantMessage(content="", tool_calls=[ToolCall(id=f"c_{name}", name=name, arguments_json=json.dumps(args))])


def say(text: str) -> AssistantMessage:
    return AssistantMessage(content=text)


def loop(llm: ScriptedLLM) -> ChatLoop:
    return ChatLoop(llm, system_prompt="SYSTEM")


async def dom_of_a12_08(re_db: str) -> str:
    [(_, dom, _)] = truth(re_db, UNIT_ROW, "A12-08")
    return str(Decimal(str(dom)).normalize())


# ---- the answer ------------------------------------------------------------------------------------------------------------


async def test_without_a_package_the_user_is_told_to_run_the_analysis_and_no_llm_is_called(alice: McpPort) -> None:
    llm = ScriptedLLM(say("không dùng"))
    text = await loop(llm).reply(QUESTION, alice, Sink())
    assert text == NO_PACKAGES_TEXT and llm.calls == []


async def test_a_tool_result_grounds_the_answer(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    dom = await dom_of_a12_08(re_db)
    llm = ScriptedLLM(ask("get_unit", unit_code="A12-08"), say(f"Căn A12-08 đã tồn {dom} ngày nhé."))
    sink = Sink()
    text = await loop(llm).reply(QUESTION, alice, sink)
    assert text == f"Căn A12-08 đã tồn {dom} ngày nhé."
    [(_, [(call, shown)])] = sink.steps
    assert call.name == "get_unit" and '"found": true' in shown
    assert llm.calls[0]["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert len(llm.calls[0]["tools"]) == 8 and llm.calls[0]["tool_choice"] == "auto"
    tool_message = llm.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == call.id and json.loads(tool_message["content"])["found"] is True


async def test_an_invented_number_is_sent_back_once_and_a_grounded_rewrite_is_accepted(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    dom = await dom_of_a12_08(re_db)
    llm = ScriptedLLM(ask("get_unit", unit_code="A12-08"), say("Căn này tồn 98765 ngày."), say(f"Căn A12-08 tồn {dom} ngày."))
    text = await loop(llm).reply(QUESTION, alice, Sink())
    assert text == f"Căn A12-08 tồn {dom} ngày." and len(llm.calls) == 3
    correction = llm.calls[2]["messages"][-1]
    assert correction["role"] == "user" and "98765" in correction["content"]  # it names the value that has no source


async def test_an_answer_that_stays_invented_is_replaced_by_a_refusal(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    llm = ScriptedLLM(ask("get_unit", unit_code="A12-08"), say("Căn này tồn 98765 ngày."))
    text = await loop(llm).reply(QUESTION, alice, Sink())
    assert text == UNGROUNDED_TEXT and "98765" not in text and len(llm.calls) == 3


async def test_the_numbers_of_a_numbered_list_are_not_figures(alice: McpPort, re_db: str) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    dom = await dom_of_a12_08(re_db)
    answer = f"Mình thấy hai điều:\n1. Căn A12-08 tồn {dom} ngày.\n2) Giá nằm trong gói.\n  3. Chưa có chiết khấu."
    llm = ScriptedLLM(ask("get_unit", unit_code="A12-08"), say(answer))
    assert await loop(llm).reply(QUESTION, alice, Sink()) == answer


async def test_a_number_that_only_looks_like_a_list_marker_is_still_checked(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    llm = ScriptedLLM(ask("get_overview"), say("Giá là 7. 654 triệu."))
    assert await loop(llm).reply(QUESTION, alice, Sink()) == UNGROUNDED_TEXT


async def test_an_identifier_no_tool_returned_is_not_accepted(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    llm = ScriptedLLM(ask("get_overview"), say("Xem gói art_deadbeef01 nhé."))
    assert await loop(llm).reply(QUESTION, alice, Sink()) == UNGROUNDED_TEXT


async def test_a_number_the_user_wrote_may_be_repeated(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    history = [{"role": "user", "content": "[from: user] Có căn nào ở tầng 77 không?"}]
    llm = ScriptedLLM(ask("list_units"), say("Trong gói này mình không thấy căn nào ở tầng 77."))
    assert await loop(llm).reply(history, alice, Sink()) == "Trong gói này mình không thấy căn nào ở tầng 77."


# ---- limits and failures ---------------------------------------------------------------------------------------------------


async def test_the_rounds_are_limited_and_the_last_one_offers_no_tools(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    llm = ScriptedLLM(ask("get_overview"))
    text = await loop(llm).reply(QUESTION, alice, Sink())
    assert text == STEP_LIMIT_TEXT and len(llm.calls) == MAX_ROUNDS
    assert [c["tool_choice"] for c in llm.calls] == ["auto"] * (MAX_ROUNDS - 1) + ["none"]


async def test_a_slow_llm_gets_an_apology_not_a_crash(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    assert await loop(ScriptedLLM(LLMTimeoutError("slow"))).reply(QUESTION, alice, Sink()) == TIMEOUT_TEXT


async def test_a_wrong_tool_call_is_answered_to_the_model(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    llm = ScriptedLLM(ask("run_sql", sql="DROP TABLE x"), say("Mình chưa tra được."))
    text = await loop(llm).reply(QUESTION, alice, Sink())
    assert text == "Mình chưa tra được."
    assert "error" in json.loads(llm.calls[1]["messages"][-1]["content"])


async def test_answering_never_queries_the_warehouse_or_writes(alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    before = len(alice.calls)
    llm = ScriptedLLM(ask("get_overview"), say("Mình đã xem tổng quan."))
    await loop(llm).reply(QUESTION, alice, Sink())
    assert set(alice.calls[before:]) <= {"artifact_list", "artifact_get"}


# ---- what the model is shown of the conversation ---------------------------------------------------------------------------


def test_only_the_chat_turns_are_kept() -> None:
    history: list[Any] = [
        {"role": "user", "content": "[from: orchestrator] {\"contract\": \"StepSpec@1\"}"},
        {"role": "assistant", "content": "Mình nhận việc…", "tool_calls": [{"id": "x", "type": "function", "function": {"name": "re_run_query", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "x", "content": "{\"rows\": 3}"},
        {"role": "assistant", "content": "Xong.\n\n```json\n{}\n```"},
        {"role": "user", "content": "[from: user] Căn A12-08 giá bao nhiêu?"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "y", "type": "function", "function": {"name": "get_unit", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "y", "content": "{}"},
        {"role": "assistant", "content": "Giá là 5 tỷ."},
        {"role": "user", "content": "[from: user] Còn căn A12-11?"},
    ]
    assert chat_turns(history) == [
        {"role": "user", "content": "Căn A12-08 giá bao nhiêu?"},
        {"role": "assistant", "content": "Giá là 5 tỷ."},
        {"role": "user", "content": "Còn căn A12-11?"},
    ]


def test_a_long_conversation_is_cut_to_the_latest_turns_starting_with_a_question() -> None:
    history: list[Any] = []
    for i in range(30):
        history += [{"role": "user", "content": f"[from: user] câu {i}"}, {"role": "assistant", "content": f"trả lời {i}"}]
    history.append({"role": "user", "content": "[from: user] câu cuối"})
    turns = chat_turns(history)
    assert turns[0]["role"] == "user" and turns[-1] == {"role": "user", "content": "câu cuối"} and len(turns) <= 13
