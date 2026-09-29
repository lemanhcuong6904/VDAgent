"""Tier 3 decision and direct reports (build spec 01 §10.3, §10.5; source §13 H1, H2, H3, H5, H8, V12; DEC-025: no timer)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmRouter
from vdagent_orchestrator.decision import USE_CURRENT, answer_decision, open_decision
from vdagent_orchestrator.dispatcher import TIMEOUT_REPLY, drive
from vdagent_orchestrator.records import RunRecord
from vdagent_orchestrator.tests.test_dispatcher import SCOPE, FakeSender, done, fail, run_of, step, REGISTRY
from vdagent_orchestrator.tests.test_replan import EXPLAIN, base, cycle, draft_json, waves
from vdagent_orchestrator.wording import PART_NAMES, card_title, no_data_sentence, timeout_sentence


def outputs_run() -> RunRecord:
    return base(step("B4", "chart", "draw_chart", ["B2", "B3"]), step("B5", "report", "draft_report", ["B2", "B3", "B4"]))


def wrong_twice(handlers: dict[str, Any]) -> tuple[RunRecord, FakeSender, FakeLLM]:
    """H1 setup: B3 WRONG_RESULT, replaced by B6 (tier 2), B6 WRONG_RESULT again."""
    llm = FakeLLM([draft_json([step("B6", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]
                                    ).model_copy(update={"replaces": "B3"})])])
    sender = FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID"),
                         "B6": lambda s: fail(s, "INSIGHT_INVALID"), "B4": done, "B5": done, **handlers})
    return cycle(outputs_run(), sender, LlmRouter([llm])), sender, llm


def test_h1_wrong_result_after_replan_decision_card_no_llm() -> None:
    run, _, llm = wrong_twice({})
    assert run.pending == [{"kind": "DECISION", "step_id": "B6"}] and not run.finished
    calls = len(llm.calls)
    card = open_decision(run)
    assert card is not None and [c.label for c in card.choices] == [USE_CURRENT, "Thử lại phần giải thích nguyên nhân"]
    assert card.title == 'Phần "Giải thích nguyên nhân" của Landmark chưa dùng được'
    assert run.status == "input_required" and run.decision_asked and len(llm.calls) == calls  # no LLM call


def test_h2_use_current_results_release_partial() -> None:
    run, sender, _ = wrong_twice({})
    open_decision(run)
    assert answer_decision(run, USE_CURRENT) == "USE_CURRENT"
    run = asyncio.run(drive(run, sender=sender, registry=REGISTRY, tier2_available=False))
    assert sender.specs["B4"].released_inputs == ["B6"] and sender.specs["B5"].released_inputs == ["B6"]
    assert run.finished and run.status == "partial"
    assert run.sales_ops_inputs == [{"kind": "DECISION", "choice": USE_CURRENT, "expired": False}]


@pytest.mark.parametrize("retry_ok", [True, False])
def test_h3_retry_success_completed_or_fail_no_second_ask(retry_ok: bool) -> None:
    run, sender, _ = wrong_twice({"B7": done if retry_ok else (lambda s: fail(s, "INSIGHT_INVALID"))})
    card = open_decision(run)
    assert card is not None and answer_decision(run, "2") == "RETRY"
    b7 = run.steps["B7"]
    assert (b7.agent, b7.operation, b7.replaces, b7.part_id) == ("insight", "explain_slow_moving", "B6", "B3")
    assert run.plan.step("B7").spec == run.plan.step("B6").spec and run.retry_reserve_used == 1
    run = asyncio.run(drive(run, sender=sender, registry=REGISTRY, tier2_available=True))
    assert waves(sender)[-3:] == [["B7"], ["B4"], ["B5"]]
    assert sender.specs["B7"].idempotency_key == "plan-1:B7"
    assert open_decision(run) is None  # never asked twice
    assert run.finished and run.status == ("completed" if retry_ok else "partial")


def test_h5_two_parts_one_card() -> None:
    run = base(step("B4", "chart", "draw_chart", ["B2"]), step("B5", "report", "draft_report", ["B2", "B3", "B4"]))
    sender = FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID"),
                         "B4": lambda s: fail(s, "WRONG_RESULT"), "B5": done})
    run = asyncio.run(drive(run, sender=sender, registry=REGISTRY, tier2_available=False))
    run.pending.append({"kind": "INPUT", "step_id": "B5"})
    assert open_decision(run) is None  # another question is out: wait
    run.pending.pop()
    card = open_decision(run)
    assert card is not None and [c.label for c in card.choices] == [
        USE_CURRENT, "Thử lại phần giải thích nguyên nhân", "Thử lại phần biểu đồ"]
    assert answer_decision(run, "Thử lại phần biểu đồ") == "RETRY"
    assert run.steps["B3"].flags == [] and run.steps["B6"].replaces == "B4"


@pytest.mark.parametrize(("code", "alert", "status"), [
    ("DATA_UNAVAILABLE", None, "failed"), ("LLM_QUOTA_EXHAUSTED", "QUOTA_EXHAUSTED", "failed"),
    ("DQ_BLOCKING", "DATA_QUALITY", "failed"), ("INTERNAL_ERROR", "FATAL", "failed"), (TIMEOUT_REPLY, "TIMEOUT", "failed"),
])
def test_h8_direct_report_classes_ops_alert(code: str, alert: str | None, status: str) -> None:
    run = run_of([step("B1", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])], pinned=True)
    run.steps["B1"].replan_used = True  # NO_DATA after tier 2
    reply = (lambda s: TIMEOUT_REPLY) if code == TIMEOUT_REPLY else (lambda s: fail(s, code))
    run = asyncio.run(drive(run, sender=FakeSender({"B1": reply}), registry=REGISTRY, tier2_available=True))
    assert run.pending == [] and open_decision(run) is None
    assert [a["kind"] for a in run.ops_alerts] == ([alert] if alert else [])
    assert run.finished and run.status == status


def test_v12_report_failure_no_replan_run_completed() -> None:
    for code in ("WRONG_RESULT", "NO_DATA"):
        run = base(step("B4", "report", "draft_report", ["B2", "B3"]))
        sender = FakeSender({"B1": done, "B2": done, "B3": done, "B4": lambda s, c=code: fail(s, c)})
        run = cycle(run, sender, LlmRouter([FakeLLM([])]))
        assert run.pending == [] and run.replan_count == 0 and not run.decision_asked
        assert run.finished and run.status == "completed" and run.steps["B4"].status == "failed"


def test_wording_templates_vi() -> None:
    assert PART_NAMES == {"data": "Số liệu", "compare": "So sánh với nhóm tương đồng", "insight": "Giải thích nguyên nhân",
                          "chart": "Biểu đồ", "report": "Báo cáo nháp"}
    assert card_title("insight", "Landmark") == 'Phần "Giải thích nguyên nhân" của Landmark chưa dùng được'
    assert no_data_sentence("giá thuê", "Landmark") == (
        "Chưa có dữ liệu giá thuê cho Landmark ở kỳ dữ liệu hiện tại. Các phần khác vẫn hiển thị.")
    assert timeout_sentence("chart") == ("Phần biểu đồ chưa xong vì xử lý quá thời gian cho phép; đội vận hành đã được báo."
                                         " Bạn có thể thử lại sau.")
    assert EXPLAIN == (["EXPLAIN"], ["CHAT_ANSWER"])
