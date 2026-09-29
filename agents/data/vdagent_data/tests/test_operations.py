"""The four operations end to end on the DW mock (S0 → S1 → operation, deterministic T1/T2)."""

from __future__ import annotations

from typing import Any

import pytest

from vdagent_data.budgets import Budget
from vdagent_data.operations import OperationResult, run_operation
from vdagent_data.pipeline.s0_intake import Intake, intake
from vdagent_data.pipeline.s1_resolve import Resolution, resolve_step
from vdagent_data.sql.templates_t2 import TEMPLATES, render_template
from vdagent_data.sql.validate import validate
from vdagent_data.tests.conftest import step
from vdagent_data.tests.fakes import DwMcp
from vdagent_contracts.scope import AuthorizedScope


async def run(mcp: DwMcp, operation: str, spec: dict[str, Any], question: str) -> OperationResult:
    s = step(operation=operation, spec=spec, original_question=question)
    got = await intake(s, mcp, user_id="u_000000000001")
    assert isinstance(got, Intake), got
    resolution = await resolve_step(s, got.spec, mcp)
    assert isinstance(resolution, Resolution), resolution
    return await run_operation(got, resolution, mcp, Budget())


def mentions(*names: tuple[str, str]) -> dict[str, Any]:
    return {"mentions": [{"text": t, "kind_hint": k} for t, k in names], "scope_all": False}


async def test_fetch_units_includes_diagnostics_and_bridge(dw_path: str) -> None:
    result = await run(DwMcp(dw_path), "fetch_units",
                       {"objective": "Căn bán chậm", "scope": mentions(("Tòa Aqua 1", "ZONE")), "filters": ["slow_moving"]},
                       "Căn nào của Tòa Aqua 1 bán chậm?")
    [entry] = result.entries
    assert entry.kind == "unit_set" and len(entry.rows) == 40
    columns = entry.columns
    assert {"unit_key", "primary_cause_code", "price_spread_vs_peer_pct", "is_peer_sample_constrained"} <= set(columns)
    diagnosed = [r for r in entry.rows if r[columns.index("price_spread_vs_peer_pct")] is not None]
    assert len(diagnosed) == 28
    assert len(entry.extra["causes"]) == 40 and entry.extra["causes"][0]["attribution_score"] == "1.000"
    assert {r.rule for r in result.dq} >= {"DQ-DUP-KEY", "DQ-MISSING-ASKING"}
    assert next(r for r in result.dq if r.rule == "DQ-MISSING-ASKING").status == "WARN"
    assert all(line["tier"] == "T2" for line in result.lineage)


async def test_aggregate_metrics_dom_by_floor_band_landmark(dw_path: str) -> None:
    result = await run(DwMcp(dw_path), "aggregate_metrics",
                       {"objective": "DOM theo nhóm tầng", "scope": mentions(("Tòa Landmark 1", "ZONE")),
                        "metrics": ["avg_dom_unsold", "unit_count"], "group_by": ["floor_band"]},
                       "DOM trung bình theo nhóm tầng của Tòa Landmark 1?")
    [entry] = result.entries
    assert entry.kind == "metric_table" and entry.extra["group_by"] == ["floor_band"]
    assert [g["floor_band"] for g in entry.extra["groups"]] == sorted(g["floor_band"] for g in entry.extra["groups"])
    assert all(m["avg_dom_unsold"]["formula_id"] == "F-DOM-01" for m in entry.metrics)
    assert result.problems == []  # groups reconcile with the total
    assert result.lineage[0]["tier"] == "T1" and len(result.lineage[0]["sql_hash"]) == 64


async def test_fetch_peer_candidates_a12_08_twelve_and_permission_filtered_count_1(dw_path: str) -> None:
    result = await run(DwMcp(dw_path), "fetch_peer_candidates",
                       {"objective": "Ứng viên peer", "scope": mentions(), "target_unit": {"text": "A12-08", "kind_hint": "UNIT"}},
                       "Tại sao căn A12-08 bán chậm?")
    [entry] = result.entries
    codes = sorted(r[entry.columns.index("unit_code")] for r in entry.rows)
    assert codes == sorted(["A12-11", "A10-02", "A14-03", "A06-01", "B09-05", "B11-07", "B15-02",
                            "C05-02", "A16-01", "A08-09", "A13-06", "A11-04"])
    assert result.extra["permissionFilteredCount"] == 1
    assert entry.extra["target"]["unit_code"] == "A12-08" and entry.extra["target"]["net_price_per_m2"] == 72_500_000


async def test_fetch_unit_context_requires_unit_set(dw_path: str) -> None:
    mcp = DwMcp(dw_path)
    units = await run(mcp, "fetch_units", {"objective": "căn", "scope": mentions(("A12-08", "UNIT"))}, "A12-08?")
    from vdagent_data.pipeline.s7_materialize import build_package, persist

    stored = await persist(mcp, build_package(operation="fetch_units", snapshot_id="SNAP-2026-09-28",
                                              semantic_config_version="sc-1", resolved={}, entries=units.entries,
                                              dq=units.dq, lineage=units.lineage, summary="x"))
    result = await run(mcp, "fetch_unit_context",
                       {"objective": "bối cảnh", "scope": mentions(), "unit_set_package_id": stored["artifact_id"],
                        "contexts": ["price_history", "macro"]}, "Bối cảnh giá?")
    assert [e.extra["context"] for e in result.entries] == ["price_history", "macro"]
    assert result.entries[0].rows and result.entries[1].rows
    with pytest.raises(LookupError):
        await run(mcp, "fetch_unit_context", {"objective": "x", "scope": mentions(), "unit_set_package_id": "art_404",
                                              "contexts": ["funnel"]}, "?")


def test_t2_template_render_params_validated() -> None:
    sql = render_template("peer_candidates_v1", {"target_unit_key": "U-PRJ-X-A12-08"})
    checked = validate(sql, snapshot_key=20260928, scope=AuthorizedScope(project_ids=["PRJ-X"]))
    assert checked.ok, checked.violations
    with pytest.raises(ValueError):
        render_template("peer_candidates_v1", {"target_unit_key": "x' OR 1=1 --"})
    with pytest.raises(KeyError):
        render_template("nope", {})
    assert all(t.reviewer for t in TEMPLATES.values())
