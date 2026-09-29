"""The four Data operations (build spec 02 §3), deterministic tiers T1/T2: each query is linted, rendered with the
locked semantic_config, executed through MCP and verified (S4–S6). T3 (free-text `extra_needs`) lives in sql/t3.py.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from vdagent_agentkit.mcp_client import McpSession
from vdagent_data.budgets import Budget
from vdagent_data.pipeline.s0_intake import Intake
from vdagent_data.pipeline.s1_resolve import SCOPE_KEY, Resolution
from vdagent_data.pipeline.s5_execute import QueryOutcome, SqlFailure, execute
from vdagent_data.pipeline.s6_verify import DqResult, Problem, check_unique_grain, compute_metrics, dq_rules, reconcile
from vdagent_data.pipeline.s7_materialize import PackageEntry
from vdagent_data.semantic.loader import LAYER
from vdagent_data.specs import AggregateMetricsSpec, FetchPeerCandidatesSpec, FetchUnitContextSpec, FetchUnitsSpec
from vdagent_data.sql.compile_t1 import SCOPE_COLUMNS, compile_t1, render
from vdagent_data.sql.templates_t2 import render_template
from vdagent_data.sql.validate import validate
from vdagent_data.value_index import Match


class OperationError(Exception):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass
class OperationResult:
    entries: list[PackageEntry] = field(default_factory=list)
    dq: list[DqResult] = field(default_factory=list)
    lineage: list[dict[str, Any]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _quote(values: list[str]) -> str:
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")"


def _where(filters: list[str], scope_filters: dict[str, list[str]]) -> str:
    parts = [f"({LAYER.filters[f].sql})".replace("{cfg.", ":").replace("}", "") for f in filters]
    parts += [f"{SCOPE_COLUMNS[k]} IN {_quote(v)}" for k, v in sorted(scope_filters.items())]
    return (" WHERE " + " AND ".join(parts)) if parts else ""


async def _query(
    session: McpSession, intake: Intake, budget: Budget, sql: str, *, name: str, tier: str,
    template_id: str | None = None, count_hidden: bool = False, keys_only: bool = False,
) -> tuple[QueryOutcome, dict[str, Any]]:
    checked = validate(sql, snapshot_key=intake.snapshot_key, scope=intake.scope, keys_only=keys_only)
    if not checked.ok or checked.sql is None:
        codes = ", ".join(f"{v.code} ({v.detail})" for v in checked.violations)
        raise OperationError("INTERNAL_ERROR", f"{tier} SQL rejected by the linter: {codes}")
    final = render(checked.sql, intake.config)
    budget.spend_sql()
    outcome = await execute(session, final, name=name, count_hidden=count_hidden)
    if isinstance(outcome, SqlFailure):
        raise OperationError("INTERNAL_ERROR", f"{tier} SQL failed: {outcome.error}")
    lineage = {
        "tier": tier, "template_id": template_id, "sql": final,
        "sql_hash": hashlib.sha256(final.encode("utf-8")).hexdigest(), "dataset_id": outcome.dataset_id,
        "snapshot_id": intake.snapshot_id, "semantic_config_version": intake.semantic_config_version,
        "tables": list(checked.tables),
    }
    return outcome, lineage


async def _fetch_units(intake: Intake, resolution: Resolution, session: McpSession, budget: Budget) -> OperationResult:
    spec = intake.spec
    assert isinstance(spec, FetchUnitsSpec)
    where = _where(spec.filters, resolution.scope_filters)
    units, l1 = await _query(session, intake, budget, render_template("units_with_diagnostics_v1", {"where": where}),
                             name="unit_set", tier="T2", template_id="units_with_diagnostics_v1")
    causes, l2 = await _query(session, intake, budget, render_template("unit_causes_v1", {"where": where}),
                              name="unit_causes", tier="T2", template_id="unit_causes_v1")
    records = units.records()
    result = OperationResult(lineage=[l1, l2], dq=dq_rules(records), problems=check_unique_grain(records, ["unit_key"]))
    result.entries.append(PackageEntry.table(kind="unit_set", dataset_id=units.dataset_id, grain="unit", rows=records,
                                             truncated=units.truncated, extra={"causes": causes.records()}))
    if not records:
        result.warnings.append("EMPTY_RESULT")
    return result


async def _aggregate(intake: Intake, resolution: Resolution, session: McpSession, budget: Budget) -> OperationResult:
    spec = intake.spec
    assert isinstance(spec, AggregateMetricsSpec)
    grouped = compile_t1(spec.metrics, spec.group_by, spec.filters, scope_filters=resolution.scope_filters)
    rows, lineage = await _query(session, intake, budget, grouped.sql, name="metric_table", tier="T1")
    result = OperationResult(lineage=[{**grouped.lineage, **lineage}])
    records = rows.records()
    if spec.group_by:
        total_sql = compile_t1(spec.metrics, [], spec.filters, scope_filters=resolution.scope_filters).sql
        total, total_lineage = await _query(session, intake, budget, total_sql, name="metric_total", tier="T1")
        result.lineage.append({**total_lineage, "purpose": "reconciliation"})
        additive = [c for c in rows.columns if c.endswith(("__num", "__den")) or c == "n"]
        result.problems += reconcile(records, total.records()[0], additive)
    metrics = compute_metrics(records, spec.metrics)
    small = sorted({name for row in metrics for name, m in row.items() if m.small_sample})
    if small:
        result.warnings.append("SMALL_SAMPLE")
        result.limitations.append(f"SMALL_SAMPLE: có nhóm dưới cỡ mẫu tối thiểu ({', '.join(small)})")
    result.entries.append(PackageEntry.metric_table(dataset_id=rows.dataset_id, grain="+".join(spec.group_by) or "total",
                                                    group_by=spec.group_by, rows=records, metrics=metrics))
    return result


async def _peer_candidates(intake: Intake, resolution: Resolution, session: McpSession, budget: Budget) -> OperationResult:
    spec = intake.spec
    assert isinstance(spec, FetchPeerCandidatesSpec) and resolution.index is not None
    target = resolution.index.resolve(spec.target_unit.text, "UNIT")
    if not isinstance(target, Match):
        raise OperationError("ENTITY_NOT_FOUND", f"Không xác định được căn mục tiêu \"{spec.target_unit.text}\".")
    params = {"target_unit_key": target.ids[0]}
    target_rows, l0 = await _query(session, intake, budget, render_template("target_unit_v1", params),
                                   name="peer_target", tier="T2", template_id="target_unit_v1")
    candidates, l1 = await _query(session, intake, budget, render_template("peer_candidates_v1", params),
                                  name="peer_candidates", tier="T2", template_id="peer_candidates_v1")
    keys, l2 = await _query(session, intake, budget, render_template("peer_candidate_keys_v1", params),
                            name="peer_candidate_keys", tier="T2", template_id="peer_candidate_keys_v1",
                            count_hidden=True, keys_only=True)
    records = candidates.records()
    result = OperationResult(lineage=[l0, l1, {**l2, "purpose": "permissionFilteredCount"}], dq=dq_rules(records),
                             problems=check_unique_grain(records, ["unit_key"]),
                             extra={"permissionFilteredCount": keys.hidden_rows or 0, "peer_count": len(records)})
    result.entries.append(PackageEntry.table(kind="peer_candidates", dataset_id=candidates.dataset_id, grain="unit",
                                             rows=records, extra={"target": target_rows.records()[0]}))
    return result


_CONTEXT_SQL = {
    "price_history": "SELECT h.unit_key, h.effective_date, h.asking_price_vnd, h.net_price_per_m2 FROM fact_unit_price_history h"
                     " WHERE h.unit_key IN {units} ORDER BY h.unit_key, h.effective_date",
    "funnel": "SELECT s.unit_key, s.date_key, s.leads, s.site_visits, s.bookings, s.cancellations, s.contracts,"
              " s.cancellation_reason FROM fact_sales_funnel_daily s WHERE s.unit_key IN {units} ORDER BY s.unit_key, s.date_key",
    "secondary_comps": "SELECT k.comp_key, k.project_key, k.unit_type, k.transaction_date, k.price_per_m2"
                       " FROM dim_secondary_market_comps k WHERE k.project_key IN {projects} ORDER BY k.comp_key",
    "macro": "SELECT a.market_id, a.segment, a.month_key, a.mortgage_rate_pct, a.absorption_rate_pct,"
             " a.months_of_inventory, a.price_to_income_ratio FROM fact_market_macro_monthly a JOIN dim_project_profile p"
             " ON p.market_id = a.market_id WHERE p.project_key IN {projects} ORDER BY a.market_id, a.month_key",
    "infrastructure": "SELECT i.asset_key, i.project_key, i.asset_type, i.asset_name, i.distance_km, i.status"
                      " FROM dim_infrastructure_assets i WHERE i.project_key IN {projects} ORDER BY i.asset_key",
}


async def _unit_context(intake: Intake, resolution: Resolution, session: McpSession, budget: Budget) -> OperationResult:
    spec = intake.spec
    assert isinstance(spec, FetchUnitContextSpec)
    outcome = await session.call_tool("artifact_get", {"artifact_id": spec.unit_set_package_id})
    if outcome.is_error:
        raise LookupError(f"unit_set package {spec.unit_set_package_id} not found")
    package = json.loads(outcome.text)["payload"]
    unit_set = next((a for a in package.get("artifacts", []) if a["kind"] == "unit_set"), None)
    if unit_set is None:
        raise LookupError(f"package {spec.unit_set_package_id} has no unit_set")
    columns = unit_set["columns"]
    units = sorted({row[columns.index("unit_key")] for row in unit_set["data"]})
    projects = sorted({row[columns.index("project_key")] for row in unit_set["data"]})
    result = OperationResult()
    for context in spec.contexts:
        sql = _CONTEXT_SQL[context].format(units=_quote(units or ["-"]), projects=_quote(projects or ["-"]))
        rows, lineage = await _query(session, intake, budget, sql, name=f"context_{context}", tier="T2",
                                     template_id=f"context_{context}_v1")
        result.lineage.append(lineage)
        result.entries.append(PackageEntry.table(kind="unit_context", dataset_id=rows.dataset_id, grain=context,
                                                 rows=rows.records(), extra={"context": context}))
    return result


_RUNNERS = {
    "fetch_units": _fetch_units,
    "aggregate_metrics": _aggregate,
    "fetch_peer_candidates": _peer_candidates,
    "fetch_unit_context": _unit_context,
}


async def run_operation(intake: Intake, resolution: Resolution, session: McpSession, budget: Budget) -> OperationResult:
    return await _RUNNERS[intake.step.operation](intake, resolution, session, budget)


__all__ = ["SCOPE_KEY", "OperationError", "OperationResult", "run_operation"]
