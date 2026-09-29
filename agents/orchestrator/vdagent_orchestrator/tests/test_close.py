"""Closing the run (build spec 01 §12 FIN-1…5; source §9 Failure Matrix)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from vdagent_contracts.intents import OutputKind
from vdagent_orchestrator.close import RunSummary, plan_failed_summary, render_markdown
from vdagent_orchestrator.dispatcher import drive, maybe_close
from vdagent_orchestrator.intent import IntentDraft, decide
from vdagent_orchestrator.records import RunRecord
from vdagent_orchestrator.tests.test_dispatcher import REGISTRY, SCOPE, FakeSender, done, fail, run_of, step

FULL = (["EXPLAIN"], ["CHAT_ANSWER", "CHART", "REPORT"])


def landmark(*, fail_at: dict[str, str] | None = None, confidence: str = "MEDIUM") -> RunRecord:
    run = run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                  step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                  step("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]),
                  step("B4", "chart", "draw_chart", ["B2", "B3"]),
                  step("B5", "report", "draft_report", ["B2", "B3", "B4"])], pinned=True, kinds=FULL)
    handlers: dict[str, Any] = {sid: done for sid in ("B1", "B3", "B4", "B5")}
    handlers["B2"] = lambda s: done(s, data_confidence=confidence)
    for sid, code in (fail_at or {}).items():
        handlers[sid] = lambda s, c=code: fail(s, c)
    return asyncio.run(drive(run, sender=FakeSender(handlers), registry=REGISTRY, tier2_available=False))


def summary(run: RunRecord) -> RunSummary:
    assert run.finished and run.summary is not None
    return RunSummary.model_validate(run.summary)


def test_fin1_close_exactly_once() -> None:
    run = landmark()
    first = run.summary
    assert maybe_close(run) is False and run.summary == first
    assert [e["event"] for e in run.events].count("RUN_FINISHED") == 1
    assert summary(run).status == "completed" and summary(run).reason == "OK"


def test_fin2_missing_outputs_walk_skipped_chain() -> None:
    run = landmark(fail_at={"B2": "DATA_UNAVAILABLE"})
    s = summary(run)
    assert s.status == "failed" and s.missing_outputs == [OutputKind.CHART, OutputKind.REPORT]
    chart = next(p for p in s.missing_parts if p.step_id == "B4")
    assert (chart.status, chart.root_step_id, chart.error_code, chart.error_class) == (
        "skipped", "B2", "DATA_UNAVAILABLE", "NO_DATA")
    assert chart.message_vi.startswith("Chưa có dữ liệu") and "Landmark" in chart.message_vi


@pytest.mark.parametrize(("fail_at", "status", "reason"), [
    ({"B1": "OUT_OF_SCOPE"}, "failed", "DATA_STEP_FAILED"),  # Data → safe failure
    ({"B2": "DQ_BLOCKING"}, "failed", "DATA_QUALITY"),
    ({"B3": "INTERNAL_ERROR"}, "partial", "ANALYTICAL_MISSING"),  # Insight / Compare / Chart → partial
    ({"B4": "NO_DATA"}, "partial", "ANALYTICAL_MISSING"),
    ({"B5": "WRONG_RESULT"}, "completed", "REPORT_MISSING"),  # Report → still runs, "thiếu báo cáo"
])
def test_fin3_status_matrix(fail_at: dict[str, str], status: str, reason: str) -> None:
    s = summary(landmark(fail_at=fail_at))
    assert (s.status, s.reason) == (status, reason)


def test_fin3_report_only_run_and_plan_failure() -> None:
    only_report = run_of([step("B1", "report", "draft_report", [])], pinned=True, kinds=(["LOOKUP"], ["REPORT"]))
    only_report = asyncio.run(drive(only_report, sender=FakeSender({"B1": lambda s: fail(s, "WRONG_RESULT")}),
                                    registry=REGISTRY, tier2_available=False))
    assert summary(only_report).status == "failed"
    draft = IntentDraft.model_validate({"scope_check": "ANALYSIS", "task_kinds": ["EXPLAIN"], "phenomena": ["bán chậm"],
                                        "mentions": [{"text": "Landmark", "kind_hint": "ZONE"}]})
    frame = decide(draft, question="Vì sao Landmark bán chậm?", served=REGISTRY.served_kinds()).frame
    assert frame is not None
    failed = plan_failed_summary(frame, "LLM_UNAVAILABLE")
    assert failed.status == "failed" and failed.reason == "LLM_UNAVAILABLE" and failed.analysis_coverage is None


def test_fin4_analysis_coverage_and_data_confidence() -> None:
    s = summary(landmark(fail_at={"B3": "INTERNAL_ERROR"}, confidence="LOW"))
    assert s.analysis_coverage == Decimal("0.500") and s.data_confidence == "LOW"  # insight failed, chart done: 1 ÷ 2
    assert summary(landmark()).analysis_coverage == Decimal("1.000")
    lookup = run_of([step("B1", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])], pinned=True)
    lookup = asyncio.run(drive(lookup, sender=FakeSender({"B1": done}), registry=REGISTRY, tier2_available=False))
    assert summary(lookup).analysis_coverage is None
    s = summary(landmark())
    assert [(p.step_id, p.agent, p.package_id) for p in s.packages][:2] == [("B1", "data", "art-B1"), ("B2", "data", "art-B2")]
    assert s.snapshot_id == "snap-0" and s.plan_version == 1 and s.replan_count == 0


def test_run_summary_markdown_vi_no_llm() -> None:
    run = landmark(fail_at={"B3": "INTERNAL_ERROR"})
    text = render_markdown(summary(run))
    body, _, technical = text.partition("Chi tiết kỹ thuật")
    assert body.startswith("**Kết quả:** Hoàn tất một phần")
    assert "Giải thích nguyên nhân" in body and "B3" not in body and "INTERNAL_ERROR" not in body
    assert "B3" in technical and "INTERNAL_ERROR" in technical and "snap-0" in technical
    assert "B1 xong" in body  # agent summaries are passed through verbatim
