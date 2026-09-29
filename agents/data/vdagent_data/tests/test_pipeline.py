"""The step state machine end to end on the DW mock: reports, error codes (build spec 02 §3), partial packages."""

from __future__ import annotations

import json
from typing import Any

import pytest

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmError, LlmErrorCode, LlmRouter
from vdagent_contracts.catalogs import load_catalog
from vdagent_contracts.errors import ErrorClass
from vdagent_data import operations
from vdagent_data.budgets import Budget
from vdagent_data.pipeline.machine import run_step
from vdagent_data.tests.conftest import step
from vdagent_data.tests.fakes import DwMcp

USER = "u_000000000001"
CATALOG = load_catalog("data")


def agg(*mentions: tuple[str, str], extra_needs: list[str] | None = None, metrics: list[str] | None = None) -> dict[str, Any]:
    return {"objective": "x", "metrics": metrics or ["avg_dom_unsold", "unit_count"], "group_by": ["floor_band"],
            "extra_needs": extra_needs or [],
            "scope": {"mentions": [{"text": t, "kind_hint": k} for t, k in mentions], "scope_all": not mentions}}


async def test_stepspec_runs_s0_to_s7_done_report(dw_path: str) -> None:
    mcp = DwMcp(dw_path)
    report = await run_step(step(spec=agg(("Tòa Landmark 1", "ZONE"))), mcp, None, user_id=USER)
    assert report.state == "completed", report
    assert report.partial == ("SMALL_SAMPLE" in report.warnings)  # small floor-band groups make it PARTIAL, never hidden
    assert (report.snapshot_id, report.semantic_config_version) == ("SNAP-2026-09-28", "sc-1")
    [ref] = report.artifact_refs
    stored = mcp.artifacts[ref.artifact_id][-1]
    assert stored["run_id"] == "t_1" and stored["payload"]["idempotency_key"] == "PLAN-1:B1"
    assert report.summary == stored["payload"]["summary"] and report.data_confidence in ("HIGH", "MEDIUM")
    assert report.usage.sql_runs >= 4
    again = await run_step(step(spec=agg(("Tòa Landmark 1", "ZONE"))), mcp, None, user_id=USER)
    assert again.artifact_refs == report.artifact_refs and len(mcp.artifacts) == 1  # idempotent


async def test_budget_exceeded_with_partial_package(dw_path: str) -> None:
    mcp = DwMcp(dw_path)
    llm = FakeLLM([])  # never reached: the LLM budget is 0
    report = await run_step(step(spec=agg(("Tòa Landmark 1", "ZONE"), extra_needs=["Số lượt xem trên sàn"])), mcp,
                            LlmRouter([llm]), user_id=USER, budget=Budget(llm_calls=0))
    assert report.state == "failed" and report.error is not None and report.error.code == "BUDGET_EXCEEDED"
    [ref] = report.artifact_refs
    stored = mcp.artifacts[ref.artifact_id][-1]
    assert stored["status"] == "PARTIAL" and any("BUDGET_EXCEEDED" in x for x in stored["limitations"])
    nothing = await run_step(step(step_id="B2", spec=agg(("Tòa Landmark 1", "ZONE"))), DwMcp(dw_path), None,
                             user_id=USER, budget=Budget(sql_runs=1))
    assert nothing.error is not None and nothing.error.code == "BUDGET_EXCEEDED" and nothing.artifact_refs == []


def _code(report: Any) -> tuple[str, str | None]:
    return report.state, (report.error.code if report.error else None)


async def test_ambiguous_and_not_found(dw_path: str) -> None:
    ambiguous = await run_step(step(spec=agg(("Landmark", "ZONE")), original_question="DOM của Landmark?"), DwMcp(dw_path), None, user_id=USER)
    assert ambiguous.state == "input_required" and ambiguous.question is not None
    assert [o.id for o in ambiguous.question.options] == ["ZN-B", "ZN-A"] and ambiguous.question.input_id == "B1:0"
    suggest = await run_step(step(spec=agg(("Tòa Aquaa 9", "ZONE")), original_question="Tòa Aquaa 9?"), DwMcp(dw_path), None, user_id=USER)
    assert suggest.state == "input_required"
    missing = await run_step(step(spec=agg(("Tòa Đồi Thông 1", "ZONE")), original_question="Tòa Đồi Thông 1?"), DwMcp(dw_path), None, user_id=USER)
    assert _code(missing) == ("failed", "ENTITY_NOT_FOUND")


@pytest.mark.parametrize("case, expected", [
    ("bad_metric", "SPEC_MISMATCH"), ("bad_operation", "OUT_OF_SCOPE"), ("no_rows", "DATA_UNAVAILABLE"),
    ("unknown_snapshot", "DQ_BLOCKING"), ("bug", "INTERNAL_ERROR"),
])
async def test_each_error_code_reported_with_class(dw_path: str, case: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    s = step(spec=agg(("Tòa Landmark 1", "ZONE")))
    if case == "bad_metric":
        s = step(spec=agg(("Tòa Landmark 1", "ZONE"), metrics=["profit"]))
    elif case == "bad_operation":
        s = step(operation="drop_units")
    elif case == "no_rows":
        s = step(spec={**agg(("Tòa Landmark 1", "ZONE")), "filters": ["sold", "available"]})
    elif case == "unknown_snapshot":
        s = step(spec=agg(("Tòa Landmark 1", "ZONE")), snapshot_id="SNAP-1999-01-01")
    else:
        async def boom(*args: Any) -> Any:
            raise ZeroDivisionError("boom")
        monkeypatch.setattr("vdagent_data.pipeline.machine.run_operation", boom)
    report = await run_step(s, DwMcp(dw_path), None, user_id=USER)
    assert _code(report) == ("failed", expected), report
    assert CATALOG.classify(expected) is not ErrorClass.FATAL or expected == "INTERNAL_ERROR"


@pytest.mark.parametrize("error, expected", [(LlmErrorCode.UNAVAILABLE, "PARTIAL"), (LlmErrorCode.QUOTA_EXHAUSTED, "PARTIAL")])
async def test_llm_failure_on_extra_need_degrades(dw_path: str, error: LlmErrorCode, expected: str) -> None:
    router = LlmRouter([FakeLLM([LlmError(error, "down"), LlmError(error, "still down")])])  # T3, then the summary
    report = await run_step(step(spec=agg(("Tòa Landmark 1", "ZONE"), extra_needs=["lượt xem"])), DwMcp(dw_path), router, user_id=USER)
    assert report.state == "completed" and report.partial and expected in report.warnings


async def test_warnings_low_confidence_small_sample_dq_warn_partial(dw_path: str) -> None:
    need_sql = "SELECT m.balcony_orientation, COUNT(*) AS n FROM fact_unit_inventory_snapshot f JOIN dim_unit_master m ON m.unit_key = f.unit_key GROUP BY m.balcony_orientation"
    other = "SELECT m.unit_type, COUNT(*) AS n FROM fact_unit_inventory_snapshot f JOIN dim_unit_master m ON m.unit_key = f.unit_key GROUP BY m.unit_type"
    llm = FakeLLM([json.dumps({"candidates": [{"sql": need_sql}, {"sql": other}]}),
                   json.dumps({"index": 0, "reason": "gần nhất"}), json.dumps({"satisfies": True, "reason": "ok"}),
                   json.dumps({"text": "Có số liệu DOM theo nhóm tầng cho phân khu đã chọn."})])
    report = await run_step(step(spec=agg(("Tòa Landmark 1", "ZONE"), extra_needs=["Số căn theo hướng ban công"])),
                            DwMcp(dw_path), LlmRouter([llm]), user_id=USER)
    assert report.state == "completed" and report.partial
    assert {"LOW_CONFIDENCE", "SMALL_SAMPLE"} <= set(report.warnings) and report.data_confidence == "LOW"
    assert report.summary == "Có số liệu DOM theo nhóm tầng cho phân khu đã chọn."


def test_operations_module_exports() -> None:
    assert callable(operations.run_operation)
