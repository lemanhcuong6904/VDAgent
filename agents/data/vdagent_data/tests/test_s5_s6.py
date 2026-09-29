"""S5 execute (via MCP, rows never go to the LLM) and S6 verify (grain, reconciliation, DQ, metrics in Decimal)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from vdagent_agentkit.testing import FakeMcp
from vdagent_data.pipeline.s5_execute import QueryOutcome, SqlFailure, execute, run_with_fixes
from vdagent_data.pipeline.s6_verify import check_unique_grain, compute_metrics, dq_rules, reconcile

ROWS = [["LOW", 3, 300], ["MID", 5, 600], ["HIGH", None, 0]]


def dataset_mcp(rows: list[list[Any]], *, fail_sql: set[str] | None = None) -> FakeMcp:
    def run(args: dict[str, Any]) -> dict[str, Any]:
        if fail_sql and args["sql"] in fail_sql:
            raise ValueError("no such column: x")
        return {"dataset_id": "ds_1", "columns": [{"name": "floor_band"}, {"name": "n"}, {"name": "dom"}],
                "row_count": len(rows), "truncated": False, "preview": rows[:2], "hidden_rows": 1}

    def page(args: dict[str, Any]) -> dict[str, Any]:
        offset, limit = args.get("offset", 0), args.get("limit", 50)
        return {"rows": rows[offset : offset + limit]}

    return FakeMcp({"re_run_query": run, "get_dataset_rows": page})


async def test_s5_calls_re_run_query_never_rows_to_llm() -> None:
    rows = [[f"U{i}", i, i * 10] for i in range(450)]
    mcp = dataset_mcp(rows)
    outcome = await execute(mcp, "SELECT 1", name="units", count_hidden=True)
    assert isinstance(outcome, QueryOutcome)
    assert outcome.rows == rows and outcome.hidden_rows == 1 and outcome.dataset_id == "ds_1"
    assert [a["offset"] for a in mcp.called("get_dataset_rows")] == [0, 200, 400]
    assert mcp.called("re_run_query") == [{"sql": "SELECT 1", "name": "units", "count_hidden": True}]
    for_llm = json.dumps(outcome.for_llm())
    assert "U17" not in for_llm and "row_count" in for_llm  # profile only, never values beyond min/max
    profile = {c["name"]: c for c in outcome.for_llm()["columns"]}
    assert profile["n"]["min"] == 0 and profile["n"]["max"] == 449 and profile["n"]["nulls"] == 0


async def test_s5_sql_error_two_fix_rounds_then_stop() -> None:
    mcp = dataset_mcp(ROWS, fail_sql={"bad0", "bad1", "bad2"})
    seen: list[str] = []

    async def fixer(sql: str, error: str) -> str:
        seen.append(error)
        return f"bad{len(seen)}"

    result = await run_with_fixes(mcp, "bad0", fixer=fixer, max_rounds=2)
    assert isinstance(result, SqlFailure) and result.rounds == 2 and len(seen) == 2
    assert "no such column" in result.error
    ok = await run_with_fixes(dataset_mcp(ROWS, fail_sql={"bad0"}), "bad0", fixer=lambda s, e: _const("good"), max_rounds=2)
    assert isinstance(ok, QueryOutcome) and ok.sql == "good" and ok.fix_rounds == 1


async def _const(value: str) -> str:
    return value


def test_s6_duplicate_grain_dq_blocking() -> None:
    rows = [{"unit_key": "U1", "v": 1}, {"unit_key": "U2", "v": 2}, {"unit_key": "U1", "v": 3}]
    problems = check_unique_grain(rows, ["unit_key"])
    assert [p.code for p in problems] == ["DQ_BLOCKING"] and "U1" in problems[0].detail
    assert check_unique_grain(rows[:2], ["unit_key"]) == []


def test_s6_reconciliation_mismatch() -> None:
    groups = [{"unit_count__num": 10}, {"unit_count__num": 5}]
    assert reconcile(groups, {"unit_count__num": 15}, ["unit_count__num"]) == []
    [problem] = reconcile(groups, {"unit_count__num": 16}, ["unit_count__num"])
    assert problem.code == "DQ_BLOCKING" and "15" in problem.detail and "16" in problem.detail


def test_s6_small_sample_warning() -> None:
    rows = [
        {"floor_band": "LOW", "avg_dom_unsold__num": 300, "avg_dom_unsold__den": 3, "n": 3},
        {"floor_band": "MID", "avg_dom_unsold__num": 610, "avg_dom_unsold__den": 10, "n": 10},
        {"floor_band": "TOP", "avg_dom_unsold__num": 0, "avg_dom_unsold__den": 0, "n": 0},
    ]
    values = compute_metrics(rows, ["avg_dom_unsold"])
    low, mid, top = (v["avg_dom_unsold"] for v in values)
    assert low.value == Decimal("100.00") and low.small_sample
    assert mid.value == Decimal("61.00") and not mid.small_sample and mid.n == 10
    assert top.value is None and top.small_sample


def test_s6_planted_dq_errors_detected() -> None:
    units = [
        {"unit_key": "U1", "inventory_status": "SOLD", "sold_date": None, "release_date": "2026-01-01",
         "snapshot_date": "2026-09-28", "net_price_per_m2": 60_000_000, "area_m2": "70.00", "asking_price_vnd": 4_700_000_000},
        {"unit_key": "U2", "inventory_status": "SOLD", "sold_date": "2025-12-01", "release_date": "2026-01-01",
         "snapshot_date": "2026-09-28", "net_price_per_m2": 60_000_000, "area_m2": "70.00", "asking_price_vnd": 4_700_000_000},
        {"unit_key": "U3", "inventory_status": "AVAILABLE", "sold_date": None, "release_date": "2026-01-01",
         "snapshot_date": "2026-09-28", "net_price_per_m2": 80_000_000, "area_m2": "70.00", "asking_price_vnd": 4_700_000_000},
        {"unit_key": "U3", "inventory_status": "AVAILABLE", "sold_date": None, "release_date": "2026-01-01",
         "snapshot_date": "2026-09-28", "net_price_per_m2": 60_000_000, "area_m2": "70.00", "asking_price_vnd": 4_700_000_000},
    ]
    results = {r.rule: r for r in dq_rules(units)}
    assert results["DQ-DUP-KEY"].status == "FAIL" and results["DQ-DUP-KEY"].affected == ["U3"]
    assert results["DQ-SOLD-DATE"].status == "WARN" and results["DQ-SOLD-DATE"].affected == ["U1", "U2"]
    assert results["DQ-NET-GT-ASKING"].status == "WARN" and results["DQ-NET-GT-ASKING"].affected == ["U3"]
    assert results["DQ-MISSING-ASKING"].status == "PASS"


def test_s6_metric_has_numerator_denominator_n() -> None:
    [row] = compute_metrics([{"absorption_rate__num": 17, "absorption_rate__den": 25, "n": 25}], ["absorption_rate"])
    metric = row["absorption_rate"]
    assert (metric.numerator, metric.denominator, metric.n, metric.formula_id) == (17, 25, 25, "F-ABS-01")
    assert metric.value == Decimal("0.6800") and metric.unit == "RATIO"
    [count] = compute_metrics([{"unit_count__num": 7, "n": 7}], ["unit_count"])
    assert count["unit_count"].value == Decimal(7) and count["unit_count"].denominator is None
