"""The Compare agent: the model plans and phrases, the engine owns every number (spec §1.9).

Driven through a recording `ctx` and a scripted JSON model; no network.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from vdagent_sdk import ToolCall

from vdagent_compare import setup
from vdagent_compare.agent import CompareAgent, OUT_OF_SCOPE
from vdagent_compare.llm import LLMUnavailableError
from vdagent_compare.phrasing import check_phrase
from vdagent_compare.settings import load_llm_settings

HERO_Q = "Tại sao A12-08 bán chậm?"

Reply = dict | Exception | Callable[[list[dict[str, Any]]], dict]


@dataclass
class FakeLLM:
    """Answers `complete_json` calls from a script keyed by schema name."""

    script: dict[str, list[Reply]]
    calls: list[tuple[str, list[dict[str, Any]]]] = field(default_factory=list)

    async def complete_json(self, messages: list[dict[str, Any]], *, name: str, schema: dict) -> dict:
        self.calls.append((name, messages))
        queue = self.script.get(name) or []
        if not queue:
            raise AssertionError(f"unexpected {name} call")
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(messages) if callable(reply) else reply

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@dataclass
class Ctx:
    history: list[dict[str, Any]]
    max_steps: int = 12
    steps: list[tuple[str, Sequence[ToolCall]]] = field(default_factory=list)
    results: list[tuple[str, str]] = field(default_factory=list)

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        self.steps.append((content, tuple(tool_calls)))

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        self.results.append((tool_call_id, content))

    @property
    def answer(self) -> str:
        return self.steps[-1][0]


def ask(question: str, *, sender: str = "user", **kw) -> Ctx:
    return Ctx(history=[{"role": "user", "content": f"[from: {sender}] {question}"}], **kw)


def plan(**fields) -> dict:
    base = {"intent": "compare", "comparisonMode": None, "subject": None, "targets": [], "metricsRequested": None,
            "cohortDimension": None, "unitTypeFilter": None, "criteriaOverride": None, "rankingOptions": None,
            "clarificationQuestion": None}
    return {**base, **fields}


HERO_PLAN = plan(comparisonMode="peer_group", subject={"entityType": "unit", "entityCode": "A12-08"})
GOOD_PHRASE = {"text": "Giá ròng/m² của A12-08 là 72.500.000 VND, cao hơn trung vị nhóm 16%; DOM 138 ngày, "
                       "xếp 6/6 trong nhóm."}


def run(agent: CompareAgent, ctx: Ctx) -> Ctx:
    asyncio.run(agent.invoke(ctx))
    return ctx


# --- the whole turn -------------------------------------------------------------------------


def test_model_plans_engine_computes_model_phrases():
    llm = FakeLLM({"comparison_plan": [HERO_PLAN], "comparison_answer": [GOOD_PHRASE]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    assert llm.names() == ["comparison_plan", "comparison_answer"]
    tool_step, final = ctx.steps
    (call,) = tool_step[1]
    assert call.name == "run_comparison"
    assert json.loads(call.arguments_json)["subject"]["entityCode"] == "A12-08"
    assert ctx.results[0][0] == call.id and '"level": "LIMITED"' in ctx.results[0][1]
    assert final[1] == ()
    assert ctx.answer.startswith("So sánh có giới hạn")  # LIMITED answers lead with their limits
    assert GOOD_PHRASE["text"] in ctx.answer
    assert "| Giá ròng/m² | 72.500.000 | 62.500.000 |" in ctx.answer  # engine table stays verbatim


def test_planner_sees_the_question_without_the_sender_prefix():
    llm = FakeLLM({"comparison_plan": [HERO_PLAN], "comparison_answer": [GOOD_PHRASE]})
    run(CompareAgent(llm=llm), ask(HERO_Q, sender="orchestrator"))
    user_text = llm.calls[0][1][-1]["content"]
    assert HERO_Q in user_text and "[from:" not in user_text


def test_invented_unit_code_is_refused_and_rules_take_over():
    invented = plan(comparisonMode="peer_group", subject={"entityType": "unit", "entityCode": "A99-99"})
    llm = FakeLLM({"comparison_plan": [invented], "comparison_answer": [GOOD_PHRASE]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    request = json.loads(ctx.steps[0][1][0].arguments_json)
    assert request["subject"]["entityCode"] == "A12-08"


def test_model_down_still_answers_with_every_number():
    llm = FakeLLM({"comparison_plan": [LLMUnavailableError("quota")],
                   "comparison_answer": [LLMUnavailableError("quota")]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    assert "62.500.000" in ctx.answer and "187,5" in ctx.answer
    assert "không dùng được mô hình ngôn ngữ" in ctx.answer


def test_plan_outside_the_schema_falls_back_to_rules():
    llm = FakeLLM({"comparison_plan": [{"intent": "compare", "subject": {"entityCode": "A12-08"}}],
                   "comparison_answer": [GOOD_PHRASE]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    assert json.loads(ctx.steps[0][1][0].arguments_json)["subject"]["entityCode"] == "A12-08"
    assert GOOD_PHRASE["text"] in ctx.answer
    assert "không dùng được mô hình" not in ctx.answer


def test_phrase_with_a_number_not_in_the_result_is_retried_then_replaced():
    bad = {"text": "Giá cao hơn nhóm 25%."}
    llm = FakeLLM({"comparison_plan": [HERO_PLAN], "comparison_answer": [bad, bad]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    assert llm.names() == ["comparison_plan", "comparison_answer", "comparison_answer"]
    assert "25%" not in ctx.answer
    assert "Kết quả Compare" in ctx.answer  # fell back to the engine's own wording


def test_second_phrase_attempt_is_used_when_it_passes():
    llm = FakeLLM({"comparison_plan": [HERO_PLAN], "comparison_answer": [{"text": "Giá cao hơn 25%."}, GOOD_PHRASE]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    retry_prompt = llm.calls[2][1][-1]["content"]
    assert "25" in retry_prompt  # the model is told what was wrong
    assert GOOD_PHRASE["text"] in ctx.answer


def test_causal_claims_are_not_published():
    causal = {"text": "A12-08 bán chậm vì giá cao hơn nhóm 16%."}
    llm = FakeLLM({"comparison_plan": [HERO_PLAN], "comparison_answer": [causal, causal]})
    ctx = run(CompareAgent(llm=llm), ask(HERO_Q))
    assert "vì giá" not in ctx.answer


def test_out_of_scope_question_is_declined_without_running_the_engine():
    llm = FakeLLM({"comparison_plan": [plan(intent="out_of_scope")]})
    ctx = run(CompareAgent(llm=llm), ask("Viết cho tôi một bài thơ"))
    assert ctx.steps == [(OUT_OF_SCOPE, ())]


def test_model_can_ask_back_with_a_closed_question():
    llm = FakeLLM({"comparison_plan": [plan(intent="clarify", clarificationQuestion="Bạn muốn so căn nào?")]})
    ctx = run(CompareAgent(llm=llm), ask("So sánh căn này"))
    assert ctx.answer == "Bạn muốn so căn nào?"
    assert ctx.results == []


def test_json_request_from_another_agent_skips_the_model():
    llm = FakeLLM({})
    request = {"subject": {"entityType": "unit", "entityCode": "A12-08"}, "comparisonMode": "peer_group"}
    ctx = run(CompareAgent(llm=llm), ask(json.dumps(request), sender="orchestrator"))
    assert llm.calls == []
    assert "62.500.000" in ctx.answer


def test_without_a_model_the_rules_answer():
    ctx = run(CompareAgent(llm=None), ask(HERO_Q))
    assert "62.500.000" in ctx.answer and len(ctx.steps) == 2


def test_one_step_budget_skips_the_tool_step():
    ctx = run(CompareAgent(llm=None), ask(HERO_Q, max_steps=1))
    assert len(ctx.steps) == 1 and ctx.steps[0][1] == ()


def test_follow_up_questions_reach_the_planner_with_earlier_turns():
    llm = FakeLLM({"comparison_plan": [plan(comparisonMode="head_to_head",
                                            subject={"entityType": "unit", "entityCode": "A12-08"},
                                            targets=[{"entityType": "unit", "entityCode": "A12-11"}])],
                   "comparison_answer": [{"text": "A12-08 so với A12-11."}]})
    ctx = Ctx(history=[
        {"role": "user", "content": f"[from: user] {HERO_Q}"},
        {"role": "assistant", "content": "…"},
        {"role": "user", "content": "[from: user] Còn so với A12-11 thì sao?"},
    ])
    run(CompareAgent(llm=llm), ctx)
    assert "A12-08" in llm.calls[0][1][-1]["content"]  # earlier turn is in the planner context
    assert json.loads(ctx.steps[0][1][0].arguments_json)["comparisonMode"] == "head_to_head"


def test_missing_data_pack_is_reported_not_crashed(tmp_path, monkeypatch):
    from vdagent_compare.vh_service import CompareService

    monkeypatch.delenv("VDAGENT_VHOP_DATA_DIR", raising=False)
    monkeypatch.setattr("vdagent_compare.vh_data.PACK_LOCATIONS", ("nowhere/vhop",))
    monkeypatch.chdir(tmp_path)
    ctx = run(CompareAgent(llm=None, service=CompareService()), ask("So sánh căn ZURICH-20.022 với căn tương đồng"))
    assert "Chưa có gói dữ liệu" in ctx.answer
    assert ctx.results and "DATA_PACK_MISSING" in ctx.results[0][1]


def test_unintelligible_question_gets_help_not_a_guess():
    llm = FakeLLM({"comparison_plan": [LLMUnavailableError("down")]})
    ctx = run(CompareAgent(llm=llm), ask("xin chào"))
    assert "Ví dụ:" in ctx.answer and ctx.results == []


# --- guard, settings, plugin entry ------------------------------------------------------------


@pytest.mark.parametrize("text,ok", [
    ("Giá cao hơn trung vị 16% (72.500.000 so với 62.500.000 VND).", True),
    ("DOM 138 ngày, cao hơn 187,5%.", True),
    ("Giá cao hơn 17%.", False),
    ("A12-08 bán chậm do giá cao.", False),
    ("Chủ đầu tư nên giảm giá.", False),
    ("Hãy tăng chiết khấu.", False),
    ("DOM của A12-08 đứng 6/6 trong 5 căn tương đồng.", True),
    ("Giá của A12-08 đắt hơn trung vị 16%.", False),  # price: only "cao hơn"/"thấp hơn" (output rules, Compare)
    ("Giá của A12-08 rẻ hơn A12-11.", False),
    ("Giá 72.500.000 là mức tốt hơn nhóm.", False),
    ("DOM 138 ngày, xấu hơn trung vị.", False),
    ("Căn đắt nhất nhóm.", False),
    ("Giá cao hơn trung vị 16%; không dùng từ chẻ hơn.", True),  # "rẻ" only as a whole word
])
def test_phrase_guard(text, ok):
    facts = "| Giá ròng/m² | 72.500.000 | 62.500.000 | 10.000.000 | 16 | 6/6 |\n| DOM | 138 | 48 | 90 | 187,5 | 6/6 |\n5 căn"
    assert (check_phrase(text, facts) == []) is ok


def test_llm_settings_default_to_luna_with_mini_fallback():
    settings = load_llm_settings({"OPENAI_API_KEY": "sk-test"})
    assert settings is not None
    assert settings.models == ("gpt-6-luna", "gpt-4o-mini")
    assert settings.openai_base_url == "https://api.openai.com/v1"


def test_no_key_or_switched_off_means_no_model():
    assert load_llm_settings({}) is None
    assert load_llm_settings({"OPENAI_API_KEY": "sk-test", "COMPARE_LLM": "off"}) is None


class _API:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register_agent(self, *, name: str, description: str, agent: Any) -> None:
        self.registered = {"name": name, "description": description, "agent": agent}


def test_plugin_loads_without_a_key(monkeypatch):
    monkeypatch.setattr("vdagent_compare.read_env", lambda: {})
    api = _API()
    setup(api, {})
    assert api.registered["name"] == "compare"
    assert api.registered["agent"].has_model is False


def test_plugin_uses_the_model_when_a_key_is_set(monkeypatch):
    monkeypatch.setattr("vdagent_compare.read_env", lambda: {"OPENAI_API_KEY": "sk-test"})
    api = _API()
    setup(api, {})
    assert api.registered["agent"].has_model is True


def test_insufficient_result_is_not_sent_to_the_model_for_wording():
    llm = FakeLLM({"comparison_plan": [plan(comparisonMode="peer_group",
                                            subject={"entityType": "unit", "entityCode": "A12-08"},
                                            criteriaOverride={"mustMatch": ["zone_id"], "areaBandPct": None})]})
    ctx = run(CompareAgent(llm=llm), ask("So sánh A12-08 với căn tương đồng cùng phân khu"))
    assert llm.names() == ["comparison_plan"]
    assert "Có thể hỏi cách khác" in ctx.answer
