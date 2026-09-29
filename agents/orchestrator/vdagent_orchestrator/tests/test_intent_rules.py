"""Clarify rules A1–A6 and default outputs (build spec 01 §4.2 INT-5, INT-7, INT-9; source §13 V20–V26)."""

from __future__ import annotations

from typing import Any

from vdagent_contracts.intents import OutputKind, TaskKind
from vdagent_orchestrator.intent import ASK_OBJECT, IntentDraft, decide

SERVED = {TaskKind.LOOKUP, TaskKind.COMPARE, TaskKind.EXPLAIN}


def draft(**fields: Any) -> IntentDraft:
    base: dict[str, Any] = {"scope_check": "ANALYSIS", "task_kinds": ["EXPLAIN"], "phenomena": ["bán chậm"],
                            "mentions": [{"text": "A12-08", "kind_hint": "UNIT"}]}
    base.update(fields)
    return IntentDraft.model_validate(base)


def run(d: IntentDraft, rounds: int = 0, question: str = "Vì sao căn A12-08 bán chậm?") -> Any:
    return decide(d, question=question, served=SERVED, clarify_rounds=rounds, metric_suggestions=["avg_dom_unsold", "absorption_rate"])


def test_a1_off_topic_rejected() -> None:  # V20
    result = run(draft(scope_check="OFF_TOPIC", task_kinds=[]), question="Soạn email cho khách")
    assert result.decision == "REJECT" and "tồn kho, giá, tốc độ bán" in result.reason


def test_a2_decision_rejected_with_rephrase() -> None:  # V21a
    result = run(draft(scope_check="DECISION_REQUEST"), question="Nên giảm giá căn A12-08 bao nhiêu?")
    assert result.decision == "REJECT" and "Vì sao căn này bán chậm?" in result.reason


def test_a2_analysis_with_decision_part_proceeds_with_assumption() -> None:  # V21b
    result = run(draft(decision_part="nên giảm giá bao nhiêu"))
    assert result.decision == "PROCEED" and any("không được thực hiện" in a for a in result.frame.assumptions)


def test_a3_unserved_kind_rejected() -> None:  # V22a
    result = run(draft(task_kinds=["TREND"]), question="Xu hướng giá A12-08 năm tới?")
    assert result.decision == "REJECT" and "TREND" in result.reason


def test_a3_partial_served_uncovered_kinds() -> None:  # V22b
    result = run(draft(task_kinds=["EXPLAIN", "TREND"]))
    assert result.decision == "PROCEED"
    assert result.frame.task_kinds == [TaskKind.EXPLAIN] and result.frame.uncovered_task_kinds == [TaskKind.TREND]
    assert any("TREND" in a for a in result.frame.assumptions)


def test_a4_no_object_ask() -> None:
    result = run(draft(mentions=[]), question="Vì sao bán chậm?")
    assert result.decision == "ASK" and result.questions == [ASK_OBJECT]


def test_a5_nothing_to_know_ask_3_suggestions() -> None:
    result = run(draft(task_kinds=[], phenomena=[], metrics=[]), question="A12-08?")
    assert result.decision == "ASK" and "A12-08" in result.questions[0] and "avg_dom_unsold, absorption_rate" in result.questions[0]


def test_a4_a5_together_max_3_questions() -> None:
    result = run(draft(mentions=[], task_kinds=[], phenomena=[]), question="Cho tôi xem")
    assert result.decision == "ASK" and len(result.questions) == 2


def test_a6_after_two_rounds_reject() -> None:  # V26: A5 asks first, A6 rejects after 2 rounds
    vague = draft(task_kinds=[], phenomena=[], metrics=[])
    assert run(vague, rounds=1).decision == "ASK"
    assert run(vague, rounds=2).decision == "REJECT"


def test_int7_default_outputs_explain() -> None:
    result = run(draft())
    assert result.frame.requested_outputs == [OutputKind.CHAT_ANSWER, OutputKind.CHART, OutputKind.REPORT]
    assert any("biểu đồ và báo cáo nháp" in a for a in result.frame.assumptions)


def test_int7_default_outputs_chat_only() -> None:
    result = run(draft(task_kinds=["LOOKUP"], metrics=["avg_dom_unsold"], phenomena=[]))
    assert result.frame.requested_outputs == [OutputKind.CHAT_ANSWER]
    explicit = run(draft(task_kinds=["LOOKUP"], metrics=["avg_dom_unsold"], requested_outputs=["CHART"]))
    assert explicit.frame.requested_outputs == [OutputKind.CHART] and explicit.frame.assumptions == []


def test_int9_mentions_passed_as_typed() -> None:
    result = run(draft(mentions=[{"text": "landmark", "kind_hint": "ZONE"}]), question="Vì sao landmark bán chậm?")
    assert [m.text for m in result.frame.mentions] == ["landmark"]


def test_v24_no_scope_no_ask() -> None:
    result = run(draft(task_kinds=["LOOKUP"], mentions=[], scope_all=True, metrics=["avg_dom_unsold"], dimensions=["zone"],
                       phenomena=[]), question="Phân khu nào có DOM trung bình cao nhất?")
    assert result.decision == "PROCEED" and result.frame.scope_all
