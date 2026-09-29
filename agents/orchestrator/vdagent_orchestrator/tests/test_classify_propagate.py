"""Error classification and handling (build spec 01 §10.1) and propagation to waiting steps (§10.2); V7, V8, V18."""

from __future__ import annotations

from typing import Any

import pytest

from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.reports import AgentReport
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.classify import classify, handling
from vdagent_orchestrator.propagate import StepView, propagate
from vdagent_orchestrator.wiring import WaitEntry

REGISTRY = CatalogRegistry.load()
REF = ArtifactRef(artifact_id="a-1", version=1, artifact_type=ArtifactType.DATA_PACKAGE)


def failed(code: str, **fields: Any) -> AgentReport:
    return AgentReport.model_validate({"state": "failed", "error": {"code": code, "message": "x"}, **fields})


@pytest.mark.parametrize(("agent", "operation", "code", "cls"), [
    ("data", "fetch_units", "ENTITY_NOT_FOUND", ErrorClass.SPEC_ISSUE),
    ("data", "fetch_units", "OUT_OF_SCOPE", ErrorClass.NO_ACCESS),
    ("data", "aggregate_metrics", "DATA_UNAVAILABLE", ErrorClass.NO_DATA),
    ("data", "aggregate_metrics", "DQ_BLOCKING", ErrorClass.DATA_QUALITY),
    ("data", "aggregate_metrics", "LLM_UNAVAILABLE", ErrorClass.TRANSIENT),
    ("data", "aggregate_metrics", "LLM_QUOTA_EXHAUSTED", ErrorClass.QUOTA_EXHAUSTED),
    ("insight", "explain_slow_moving", "INSIGHT_INVALID", ErrorClass.WRONG_RESULT),
    ("insight", "explain_slow_moving", "INTERNAL_ERROR", ErrorClass.FATAL),
])
def test_classify_table_each_class(agent: str, operation: str, code: str, cls: ErrorClass) -> None:
    outcome = classify(failed(code), agent=agent, operation=operation, registry=REGISTRY)
    assert outcome.kind == "ERROR" and outcome.error_class is cls and outcome.code == code
    question = AgentReport.model_validate({"state": "input_required", "question": {"text": "Căn nào?"}})
    assert classify(question, agent="data", operation="fetch_units", registry=REGISTRY).error_class is ErrorClass.NEED_INPUT
    canceled = classify(failed("DATA_UNAVAILABLE"), agent="data", operation="fetch_units", registry=REGISTRY, run_canceled=True)
    assert canceled.error_class is ErrorClass.CANCELED
    done = classify(AgentReport(state="completed", warnings=["LOW_CONFIDENCE"]), agent="data", operation="fetch_units",
                    registry=REGISTRY)
    assert done.kind == "DONE" and done.warnings == ("LOW_CONFIDENCE",)


def test_handling_per_class() -> None:
    assert handling(ErrorClass.NEED_INPUT, "data", tier2_available=True).action == "ASK_SALES_OPS"
    assert handling(ErrorClass.WRONG_RESULT, "insight", tier2_available=True).action == "REPLAN"
    assert handling(ErrorClass.WRONG_RESULT, "insight", tier2_available=False).action == "DECISION"
    assert handling(ErrorClass.NO_DATA, "insight", tier2_available=False).action == "REPORT_DIRECT"
    assert handling(ErrorClass.WRONG_RESULT, "report", tier2_available=True).action == "REPORT_DIRECT"  # OUTPUT group
    quality = handling(ErrorClass.DATA_QUALITY, "data", tier2_available=True)
    assert quality.action == "REPORT_DIRECT" and quality.ops_alert and quality.run_fails
    access = handling(ErrorClass.NO_ACCESS, "data", tier2_available=True)
    assert access.action == "REPORT_DIRECT" and not access.ops_alert
    for cls in (ErrorClass.TRANSIENT, ErrorClass.QUOTA_EXHAUSTED, ErrorClass.FATAL):
        assert handling(cls, "insight", tier2_available=True).ops_alert
    assert handling(ErrorClass.CANCELED, "data", tier2_available=True).action == "CANCEL"


def test_classify_unknown_code_fatal() -> None:  # V7
    outcome = classify(failed("SOMETHING_NEW"), agent="data", operation="fetch_units", registry=REGISTRY)
    assert outcome.error_class is ErrorClass.FATAL


def test_budget_exceeded_with_partial_is_done_warning() -> None:  # V8a
    report = failed("BUDGET_EXCEEDED", artifact_refs=[REF.model_dump(mode="json")], partial=True)
    outcome = classify(report, agent="data", operation="aggregate_metrics", registry=REGISTRY)
    assert outcome.kind == "DONE" and "BUDGET_EXCEEDED" in outcome.warnings and outcome.partial


def test_budget_exceeded_without_partial_spec_issue() -> None:  # V8b
    outcome = classify(failed("BUDGET_EXCEEDED"), agent="data", operation="aggregate_metrics", registry=REGISTRY)
    assert outcome.kind == "ERROR" and outcome.error_class is ErrorClass.SPEC_ISSUE


def view(step_id: str, *waits: tuple[str, str], status: str = "pending") -> StepView:
    return StepView(step_id, status, tuple(WaitEntry(step_id=s, mode=m) for s, m in waits))  # type: ignore[arg-type]


def test_v18_hard_skip_soft_release() -> None:
    steps = [view("B3", status="failed"), view("B4", ("B3", "HARD")), view("B5", ("B4", "SOFT"), ("B2", "HARD"))]
    actions = propagate("B3", "DIRECT", steps)
    assert [(a.kind, a.step_id, a.from_step) for a in actions] == [("SKIP_CANCEL", "B4", "B3"), ("RELEASE", "B5", "B4")]
    assert [a.kind for a in propagate("B3", "AWAITING", steps)] == ["KEEP_WAITING"]
    rewired = propagate("B3", "REPLACED", steps, replacement="B6")
    assert [(a.kind, a.step_id, a.from_step, a.to_step) for a in rewired] == [("REWIRE", "B4", "B3", "B6")]


def test_propagate_recursive_skipped() -> None:
    steps = [view("B1", status="failed"), view("B2", ("B1", "HARD")), view("B3", ("B2", "HARD")),
             view("B4", ("B3", "HARD"), ("B1", "SOFT")), view("B5", ("B4", "SOFT")),
             view("B6", ("B1", "HARD"), status="completed")]  # terminal steps are left alone
    actions = propagate("B1", "DIRECT", steps)
    assert [(a.kind, a.step_id, a.from_step) for a in actions] == [
        ("SKIP_CANCEL", "B2", "B1"), ("RELEASE", "B4", "B1"), ("SKIP_CANCEL", "B3", "B2"), ("SKIP_CANCEL", "B4", "B3"),
        ("RELEASE", "B5", "B4")]
