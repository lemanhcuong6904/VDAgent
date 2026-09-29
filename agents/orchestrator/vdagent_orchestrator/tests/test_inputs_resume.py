"""Agent questions and clarification, turn based (build spec 01 §10.4, INT-6; DEC-025, DEC-027; source §13 V1, V2, V11, H9)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmRouter
from vdagent_agentkit.testing import InMemoryMemory
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_orchestrator.inputs import NONE_OF_THESE, answer, open_question
from vdagent_orchestrator.llm1 import understand
from vdagent_orchestrator.records import RunRecord
from vdagent_orchestrator.run_state import Awaiting, ConversationState, load_state, route_message, save_state
from vdagent_orchestrator.tests.test_dispatcher import REGISTRY, SCOPE, FakeSender, done, go, run_of, step


def ask(spec: StepSpec, n: int = 0) -> AgentReport:
    return AgentReport(run_id=spec.run_id, step_id=spec.step_id, idempotency_key=spec.idempotency_key,
                       state="input_required", summary="Có 2 phân khu tên gần giống.",
                       question={"text": "Bạn muốn xem phân khu nào?", "input_id": f"{spec.step_id}:{n}",  # type: ignore[arg-type]
                                 "options": [{"id": "ZN-A", "label": "Tòa Landmark 1"}, {"id": "ZN-B", "label": "Landmark Plaza"}]})


def asks_until_answered(spec: StepSpec) -> AgentReport:
    return done(spec) if any(a.input_id == f"{spec.step_id}:0" for a in spec.answered_choices) else ask(spec)


def one_data_step() -> RunRecord:
    return run_of([step("B1", "data", "fetch_units", scope=SCOPE)], pinned=True)


def test_v1_data_ambiguous_card_two_choices_plus_none() -> None:
    run = go(one_data_step(), FakeSender({"B1": ask}))
    card = open_question(run)
    assert card is not None and card.input_id == "B1:0" and card.step_id == "B1"
    assert [c.label for c in card.choices] == ["Tòa Landmark 1", "Landmark Plaza", NONE_OF_THESE]
    assert run.status == "input_required" and not run.finished and run.agent_questions == 1
    assert open_question(run) is card or open_question(run) == card  # asking again does not count twice
    assert run.agent_questions == 1


def test_v1_answer_resumes_step_with_choice() -> None:
    sender = FakeSender({"B1": asks_until_answered})
    run = go(one_data_step(), sender)
    assert open_question(run) is not None
    result = answer(run, "Landmark Plaza")
    assert result == "RESUMED" and run.status == "working" and run.steps["B1"].status == "working"
    run = go(run, sender)
    assert [(a.input_id, a.choice) for a in sender.specs["B1"].answered_choices] == [("B1:0", "ZN-B")]
    assert sender.specs["B1"].idempotency_key == "plan-1:B1"  # same step, same key
    assert run.finished and run.status == "completed"
    by_number = go(one_data_step(), FakeSender({"B1": ask}))
    assert answer(by_number, "2") == "NOT_AWAITING"  # no card shown yet
    open_question(by_number)
    assert answer(by_number, "2") == "RESUMED"  # choice by number


def test_v2_none_of_these_cancels_step_direct_report() -> None:
    run = go(one_data_step(), FakeSender({"B1": ask}))
    open_question(run)
    assert answer(run, NONE_OF_THESE) == "CANCELED"
    b1 = run.steps["B1"]
    assert b1.status == "canceled" and b1.error_code == "INPUT_DECLINED" and "tên rõ hơn" in (b1.error_message or "")
    assert run.finished and run.status == "failed"


def test_v2_third_agent_question_cancels() -> None:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                  step("B3", "data", "aggregate_metrics", scope=SCOPE, metrics=["unit_count"])], pinned=True)
    sender = FakeSender({"B1": asks_until_answered, "B2": asks_until_answered, "B3": asks_until_answered})
    run = go(run, sender)
    for expected in ("B1:0", "B2:0"):
        card = open_question(run)
        assert card is not None and card.input_id == expected
        assert answer(run, "Tòa Landmark 1") == "RESUMED"
    assert open_question(run) is None  # the 3rd question of the run is not asked
    b3 = run.steps["B3"]
    assert b3.status == "canceled" and b3.error_code == "TOO_MANY_QUESTIONS" and run.agent_questions == 2
    run = go(run, sender)
    assert run.steps["B1"].status == "completed" and run.steps["B2"].status == "completed"


def test_v11_second_question_same_step_counts() -> None:
    calls: list[int] = []

    def twice(spec: StepSpec) -> AgentReport:
        calls.append(1)
        answered = {a.input_id for a in spec.answered_choices}
        if "B1:0" not in answered:
            return ask(spec, 0)
        return ask(spec, 1) if "B1:1" not in answered else done(spec)

    sender = FakeSender({"B1": twice})
    run = go(one_data_step(), sender)
    assert open_question(run).input_id == "B1:0"  # type: ignore[union-attr]
    answer(run, "1")
    run = go(run, sender)
    card = open_question(run)
    assert card is not None and card.input_id == "B1:1" and run.agent_questions == 2
    assert run.steps["B1"].question is not None and run.steps["B1"].question.input_id == "B1:1"


def test_h9_reply_when_nothing_pending_is_new_question() -> None:
    assert route_message(ConversationState(), "Vì sao Landmark bán chậm?") == "NEW_QUESTION"
    finished = go(run_of([step("B1", "data", "fetch_units", scope=SCOPE)], pinned=True), FakeSender({"B1": done}))
    assert route_message(ConversationState(run=finished), "1") == "NEW_QUESTION"
    waiting = go(one_data_step(), FakeSender({"B1": ask}))
    card = open_question(waiting)
    state = ConversationState(run=waiting, awaiting=Awaiting(kind="AGENT_QUESTION", input_id=card.input_id))  # type: ignore[union-attr]
    assert route_message(state, "Landmark Plaza") == "ANSWER"
    clarify = ConversationState(awaiting=Awaiting(kind="CLARIFY", question="Vì sao bán chậm?", questions=["Phạm vi?"]))
    assert route_message(clarify, "Landmark") == "CLARIFY_ANSWER"


def test_clarify_answer_replans_with_all_answers() -> None:
    state = ConversationState(awaiting=Awaiting(kind="CLARIFY", question="Vì sao bán chậm?", answers=["phân khu"],
                                                questions=["Bạn muốn xem dự án, phân khu hay căn nào?"], rounds=1))
    question, answers, rounds = state.awaiting.resume_clarify("Landmark")  # type: ignore[union-attr]
    assert (question, answers, rounds) == ("Vì sao bán chậm?", ["phân khu", "Landmark"], 1)
    llm = FakeLLM([json.dumps({"scope_check": "ANALYSIS", "task_kinds": ["EXPLAIN"], "phenomena": ["bán chậm"],
                               "mentions": [{"text": "Landmark", "kind_hint": "ZONE"}]})])
    result = asyncio.run(understand(question, router=LlmRouter([llm]), registry=REGISTRY, clarify_answers=answers))
    user = llm.calls[0]["messages"][1]["content"]
    assert "phân khu" in user and "Landmark" in user and "Vì sao bán chậm?" in user
    assert [m.text for m in result.draft.mentions] == ["Landmark"]  # the answer counts as the user's words


def test_run_state_roundtrip_in_memory() -> None:
    memory = InMemoryMemory()
    waiting = go(one_data_step(), FakeSender({"B1": ask}))
    card = open_question(waiting)
    state = ConversationState(run=waiting, awaiting=Awaiting(kind="AGENT_QUESTION", input_id=card.input_id))  # type: ignore[union-attr]
    asyncio.run(save_state(memory, state))
    asyncio.run(save_state(memory, state))
    loaded: Any = asyncio.run(load_state(memory))
    assert loaded == state and len(asyncio.run(memory.recent(10))) == 1  # older states are replaced
    assert asyncio.run(load_state(InMemoryMemory())) == ConversationState()
