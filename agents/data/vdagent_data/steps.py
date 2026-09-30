"""Deterministic StepSpec operations of the Data agent over the real-estate DW (WS2, D1/D2/D4/D8/D9).

`run_step(step, tools)` answers one `StepSpec@1` without any LLM:

1. Validate the operation and its spec; require an explicit snapshot and semantic config version.
2. Resolve the caller's scope from the Backend (`get_user_context`), never from the step.
3. Pin the snapshot: it must exist in `snapshot_manifest`, be APPROVED and carry the requested semantic version.
   A DRAFT, unknown or "latest" snapshot is rejected; nothing is substituted.
4. Read `re_warehouse` through `re_run_query` only (the Backend's scoped views hide rows outside the scope).
5. Store `dataset` (re_dataset@1), `metric` (re_metric@1) and `dq` (re_dq@1) through `artifact_put`; metric and dq
   pin the dataset by `content_hash`, so the store checks their lineage (WS1).

Missing values stay `null` with a limitation code (docs/integration/CANONICAL_DATA_CONTRACT.md §7); nothing is
defaulted to 0. The peer area is `net_area_m2` only (D9, `vdagent_contracts.peer_rules`). Blocked semantics (D2b
segment mapping, PENDING `min_group_size`) are passed through raw and flagged, never mapped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vdagent_contracts.canonical import canonical_json, percentile_inc
from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.peer_rules import PEER_AREA_FIELD, PeerAreaUnavailable, area_tolerance_ratio, peer_area
from vdagent_contracts.reports import AgentReport, QuestionOption, ReportError, ReportQuestion

log = logging.getLogger(__name__)

AGENT = "data"
AGENT_VERSION = "0.2.0"
FUNNEL_WINDOW_DAYS = 30
PAGE_ROWS = 200
CONFIG_KEYS = ("peer_area_tolerance_pct", "min_group_size", "overdue_threshold_days")

# Error code → the class the Orchestrator acts on (contracts/vdagent_contracts/errors.py).
DATA_ERROR_CLASSES: dict[str, ErrorClass] = {
    "INVALID_STEPSPEC": ErrorClass.SPEC_ISSUE,
    "UNSUPPORTED_CONTRACT": ErrorClass.SPEC_ISSUE,
    "UNKNOWN_OPERATION": ErrorClass.SPEC_ISSUE,
    "INVALID_SPEC": ErrorClass.SPEC_ISSUE,
    "UNKNOWN_METRIC": ErrorClass.SPEC_ISSUE,
    "SNAPSHOT_REQUIRED": ErrorClass.SPEC_ISSUE,
    "SNAPSHOT_UNKNOWN": ErrorClass.SPEC_ISSUE,
    "SNAPSHOT_NOT_APPROVED": ErrorClass.SPEC_ISSUE,
    "SEMANTIC_VERSION_REQUIRED": ErrorClass.SPEC_ISSUE,
    "SEMANTIC_VERSION_MISMATCH": ErrorClass.SPEC_ISSUE,
    "USER_CONTEXT_MISMATCH": ErrorClass.NO_ACCESS,
    "UNIT_NOT_FOUND": ErrorClass.NO_DATA,
    "EMPTY_POPULATION": ErrorClass.NO_DATA,
    "UNIT_AMBIGUOUS": ErrorClass.NEED_INPUT,
    "SUBJECT_AREA_UNAVAILABLE": ErrorClass.DATA_QUALITY,
    "RESULT_TRUNCATED": ErrorClass.DATA_QUALITY,
    "TOOL_FAILED": ErrorClass.TRANSIENT,
    "INTERNAL_ERROR": ErrorClass.FATAL,
}

_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")  # snapshot ids, unit codes, keys, enum values

# ---- ports -------------------------------------------------------------------------------------------------------


class ToolFailure(Exception):
    """An MCP tool answered with an error."""


class Tools(Protocol):
    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call one Backend MCP tool; return its JSON result or raise `ToolFailure`."""
        ...


class StepError(Exception):
    def __init__(self, state: Literal["rejected", "failed"], code: str, message: str, question: ReportQuestion | None = None) -> None:
        super().__init__(message)
        self.state, self.code, self.message, self.question = state, code, message, question


# ---- specs -------------------------------------------------------------------------------------------------------

_SPEC = ConfigDict(extra="forbid", frozen=True)
GROUP_COLUMNS = ("project_key", "zone_key", "unit_type", "floor_band", "launch_batch_id", "inventory_status")


def _ident(value: str) -> str:
    if not _IDENT.fullmatch(value):
        raise ValueError(f"not a valid identifier: {value!r}")
    return value


class FetchUnitsSpec(BaseModel):
    model_config = _SPEC

    subject_unit_code: str
    population: Literal["subject", "peer_candidates"] = "subject"
    project_ids: list[str] = Field(default_factory=list)  # narrows the subject lookup; the scope still applies

    @field_validator("subject_unit_code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        return _ident(v)

    @field_validator("project_ids")
    @classmethod
    def _check_projects(cls, v: list[str]) -> list[str]:
        return [_ident(p) for p in v]


class AggregateSpec(BaseModel):
    model_config = _SPEC

    metrics: list[str] = Field(min_length=1)
    group_by: list[Literal["project_key", "zone_key", "unit_type", "floor_band", "launch_batch_id", "inventory_status"]] = Field(default_factory=list)
    filters: dict[Literal["project_key", "zone_key", "unit_type", "floor_band", "launch_batch_id", "inventory_status"], str] = Field(default_factory=dict)

    @field_validator("filters")
    @classmethod
    def _check_filters(cls, v: dict[str, str]) -> dict[str, str]:
        return {k: _ident(x) for k, x in v.items()}


@dataclass(frozen=True)
class MetricDef:
    unit: str
    source: str | None  # "table.column"; None = no DW source (always null + METRIC_UNAVAILABLE)
    calculation_ref: str


# Metrics Data can name. `source=None` marks metrics the DW does not hold (D8: null + limitation, never 0).
METRICS: dict[str, MetricDef] = {
    "dom_days": MetricDef("DAY", "fact_unit_inventory_snapshot.unsold_days_dom", "calc_dom_days@1"),
    "net_price_per_m2_vnd": MetricDef("VND_PER_M2", "fact_unit_inventory_snapshot.net_price_per_m2", "calc_net_price_per_m2@1"),
    "asking_price_vnd": MetricDef("VND", "fact_unit_inventory_snapshot.asking_price_vnd", "calc_asking_price@1"),
    "net_area_m2": MetricDef("M2", "dim_unit_master.net_area_m2", "calc_net_area_m2@1"),
    "inquiry_leads_30d": MetricDef("COUNT", "fact_sales_funnel_daily.leads", "calc_inquiry_leads_30d@1"),
    "subsidy_duration_mo": MetricDef("COUNT", "dm_unit_friction_diagnostics.subsidy_duration_mo", "calc_subsidy_duration@1"),
    "dw_peer_n": MetricDef("COUNT", "dm_unit_friction_diagnostics.peer_n", "dw_peer_n@1"),
    "discount_pct": MetricDef("PCT", None, "calc_discount_pct@1"),
}
UNIT_METRICS = ("dom_days", "net_price_per_m2_vnd", "asking_price_vnd", "net_area_m2", "inquiry_leads_30d",
                "subsidy_duration_mo", "discount_pct", "dw_peer_n")
AGGREGATABLE = ("dom_days", "net_price_per_m2_vnd", "asking_price_vnd", "net_area_m2")

# ---- helpers -----------------------------------------------------------------------------------------------------


def _q(value: str) -> str:
    return "'" + _ident(value).replace("'", "''") + "'"


def _in(values: Iterable[str]) -> str:
    items = sorted(set(values))
    return "(" + ", ".join(_q(v) for v in items) + ")" if items else "(NULL)"


def _sha(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _date_key(day: date) -> int:
    return int(day.strftime("%Y%m%d"))


def _day(date_key: int) -> date:
    return date(date_key // 10000, date_key // 100 % 100, date_key % 100)


def _pct(part: int, total: int) -> str:
    return str((Decimal(part) * 100 / Decimal(total)).quantize(Decimal("0.01"))) if total else "0.00"


@dataclass
class _Run:
    step: StepSpec
    tools: Tools
    snapshot_id: str = ""
    snapshot_date_key: int = 0
    loaded_at: str = ""
    semantic: str = ""
    queries: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    async def select(self, table: str, sql: str) -> list[dict[str, Any]]:
        """All rows of one scoped SELECT (paged), recorded by SQL hash; a truncated result is an error, not data.
        Out-of-scope rows are never counted or recorded (WS7 F-08): the artifact holds authorized rows only."""
        res = await self.tools.call("re_run_query", {"sql": sql})
        if res.get("truncated"):
            raise StepError("failed", "RESULT_TRUNCATED", f"query on {table} exceeded the row cap; narrow the request")
        columns = [c["name"] for c in res["columns"]]
        rows: list[list[Any]] = list(res["preview"])
        while len(rows) < res["row_count"]:
            page = await self.tools.call("get_dataset_rows", {"dataset_id": res["dataset_id"], "offset": len(rows), "limit": PAGE_ROWS})
            if not page["rows"]:
                break
            rows.extend(page["rows"])
        self.queries.append({"table": table, "sql_sha256": _sha(sql), "row_count": len(rows)})
        if f"re:{table}" not in self.sources:
            self.sources.append(f"re:{table}")
        return [dict(zip(columns, r, strict=True)) for r in rows]

    async def put(self, kind: ArtifactType, schema: str, payload: dict[str, Any], limitations: Sequence[str],
                  inputs: Sequence[ArtifactRef] = (), *, partial: bool = False) -> tuple[ArtifactRef, str]:
        status = "PARTIAL" if partial and limitations else "VALID"
        draft = {
            "artifact_type": kind.value, "schema_version": schema, "status": status,
            "producer": {"agent": AGENT, "agent_version": AGENT_VERSION},
            "snapshot_refs": [self.snapshot_id], "semantic_config_version": self.semantic,
            "source_refs": list(self.sources), "input_artifact_refs": [r.model_dump(mode="json") for r in inputs],
            "limitations": sorted(set(limitations)), "payload": payload,
        }
        stored = await self.tools.call("artifact_put", {"draft_json": canonical_json(draft)})
        ref = ArtifactRef(artifact_id=stored["artifact_id"], version=stored["version"], artifact_type=kind,
                          content_hash=stored["content_hash"])
        return ref, stored["status"]


# ---- entry point -------------------------------------------------------------------------------------------------


async def run_step(step: StepSpec, tools: Tools) -> AgentReport:
    """Answer one StepSpec; every failure becomes a structured AgentReport, never an exception."""
    try:
        return await _run(step, tools)
    except StepError as exc:
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message,
                                                         retryable=DATA_ERROR_CLASSES[exc.code] is ErrorClass.TRANSIENT),
                       question=exc.question)
    except ToolFailure as exc:
        return _report(step, "failed", error=ReportError(code="TOOL_FAILED", message=str(exc), retryable=True))
    except Exception as exc:  # a bug: reported, never raised into the Backend turn
        log.exception("data: step %s failed", step.idempotency_key)
        return _report(step, "failed", error=ReportError(code="INTERNAL_ERROR", message=type(exc).__name__))


def rejection(code: str, message: str) -> AgentReport:
    """A report for a message that is not a valid StepSpec (no run/step identity available)."""
    return AgentReport(state="rejected", error=ReportError(code=code, message=message), summary=message)


def _report(step: StepSpec, state: str, *, error: ReportError | None = None, question: ReportQuestion | None = None,
            refs: Sequence[ArtifactRef] = (), warnings: Sequence[str] = (), partial: bool = False,
            summary: str = "") -> AgentReport:
    return AgentReport.model_validate({
        "run_id": step.run_id, "step_id": step.step_id, "idempotency_key": step.idempotency_key,
        "state": "input_required" if question is not None else state, "partial": partial,
        "artifact_refs": [r.model_dump(mode="json") for r in refs],
        "snapshot_id": step.snapshot_id, "semantic_config_version": step.semantic_config_version,
        "summary": summary or (error.message if error else ""), "warnings": sorted(set(warnings)),
        "error": None if question is not None else error,
        "question": question,
    })


async def _run(step: StepSpec, tools: Tools) -> AgentReport:
    spec = _parse_spec(step)
    if not step.snapshot_id:
        raise StepError("rejected", "SNAPSHOT_REQUIRED", "a snapshot_id is required; no default or latest snapshot is used")
    if not step.semantic_config_version:
        raise StepError("rejected", "SEMANTIC_VERSION_REQUIRED", "a semantic_config_version is required")
    if not _IDENT.fullmatch(step.snapshot_id) or not _IDENT.fullmatch(step.semantic_config_version):
        raise StepError("rejected", "SNAPSHOT_UNKNOWN", f"unknown snapshot {step.snapshot_id!r}")

    caller = await tools.call("get_user_context", {})
    if caller.get("user_id") != step.user_context.user_id:
        raise StepError("rejected", "USER_CONTEXT_MISMATCH", "the step's user_context is not the calling user")

    run = _Run(step, tools)
    await _pin_snapshot(run)
    config, config_limits = await _semantic_config(run)
    if isinstance(spec, FetchUnitsSpec):
        return await _fetch_units(run, spec, config, config_limits)
    return await _aggregate(run, spec, config, config_limits)


def _parse_spec(step: StepSpec) -> FetchUnitsSpec | AggregateSpec:
    model = {"fetch_units": FetchUnitsSpec, "aggregate_metrics": AggregateSpec}.get(step.operation)
    if model is None:
        raise StepError("rejected", "UNKNOWN_OPERATION", f"unknown operation {step.operation!r}; use fetch_units or aggregate_metrics")
    try:
        spec = model.model_validate(step.spec)
    except ValidationError as exc:
        raise StepError("rejected", "INVALID_SPEC", f"invalid {step.operation} spec: {exc.error_count()} error(s)") from None
    if isinstance(spec, AggregateSpec):
        unknown = [m for m in spec.metrics if m not in METRICS]
        if unknown:
            raise StepError("rejected", "UNKNOWN_METRIC", f"unknown metric(s): {', '.join(unknown)}")
    return spec


async def _pin_snapshot(run: _Run) -> None:
    step = run.step
    assert step.snapshot_id and step.semantic_config_version
    rows = await run.select(
        "snapshot_manifest",
        "SELECT snapshot_id, snapshot_date_key, status, semantic_config_version, loaded_at FROM snapshot_manifest"
        f" WHERE snapshot_id = {_q(step.snapshot_id)}",
    )
    if not rows:
        raise StepError("rejected", "SNAPSHOT_UNKNOWN", f"unknown snapshot {step.snapshot_id!r}")
    manifest = rows[0]
    if manifest["status"] != "APPROVED":
        raise StepError("rejected", "SNAPSHOT_NOT_APPROVED",
                        f"snapshot {step.snapshot_id} is {manifest['status']}; only APPROVED snapshots are served")
    if manifest["semantic_config_version"] != step.semantic_config_version:
        raise StepError("rejected", "SEMANTIC_VERSION_MISMATCH",
                        f"snapshot {step.snapshot_id} uses semantic config {manifest['semantic_config_version']},"
                        f" not {step.semantic_config_version}")
    run.snapshot_id, run.semantic = step.snapshot_id, step.semantic_config_version
    run.snapshot_date_key, run.loaded_at = manifest["snapshot_date_key"], manifest["loaded_at"]


async def _semantic_config(run: _Run) -> tuple[dict[str, Any], list[str]]:
    rows = await run.select(
        "semantic_config",
        "SELECT config_key, config_value, status FROM semantic_config"
        f" WHERE config_version = {_q(run.semantic)} AND config_key IN {_in(CONFIG_KEYS)}",
    )
    config: dict[str, Any] = {}
    limitations: list[str] = []
    for row in rows:
        value = json.loads(row["config_value"], parse_float=Decimal)
        entry: dict[str, Any] = {"value": value, "status": row["status"]}
        if row["config_key"] == "peer_area_tolerance_pct":
            entry["ratio"] = str(area_tolerance_ratio(value))  # D9 companion rule: a ratio, 0.10 = 10 %
        if row["status"] != "APPROVED":
            limitations.append(f"CONFIG_PENDING:{row['config_key']}")  # passed through, never defaulted
        config[row["config_key"]] = entry
    return config, limitations


# ---- fetch_units -------------------------------------------------------------------------------------------------


async def _fetch_units(run: _Run, spec: FetchUnitsSpec, config: dict[str, Any], limitations: list[str]) -> AgentReport:
    key = run.snapshot_date_key
    where = f"unit_code = {_q(spec.subject_unit_code)}"
    if spec.project_ids:
        where += f" AND project_key IN {_in(spec.project_ids)}"
    found = await run.select("dim_unit_master", f"SELECT * FROM dim_unit_master WHERE {where} ORDER BY project_key")
    if not found:
        raise StepError("failed", "UNIT_NOT_FOUND", f"unit {spec.subject_unit_code} was not found in your authorized scope")
    if len(found) > 1:
        options = [QuestionOption(id=u["unit_key"], label=f"{u['unit_code']} ({u['project_key']})") for u in found]
        raise StepError("failed", "UNIT_AMBIGUOUS", f"{len(found)} units match {spec.subject_unit_code}",
                        ReportQuestion(text=f"Có {len(found)} căn {spec.subject_unit_code}. Bạn muốn căn nào?", options=options))
    subject = found[0]
    try:
        peer_area(subject)
    except PeerAreaUnavailable as exc:
        raise StepError("failed", "SUBJECT_AREA_UNAVAILABLE", f"{spec.subject_unit_code}: {exc}; area_m2 is never used instead") from None

    considered = [subject]
    excluded: list[dict[str, str]] = []
    if spec.population == "peer_candidates":
        # Candidate population only (same unit type, inside the scope). Peer *selection* is Compare's (WS3).
        others = await run.select(
            "dim_unit_master",
            f"SELECT * FROM dim_unit_master WHERE unit_type = {_q(subject['unit_type'])}"
            f" AND unit_key <> {_q(subject['unit_key'])} ORDER BY unit_code, unit_key",
        )
        considered += others
    units = [subject]
    for unit in considered[1:]:
        try:
            peer_area(unit)
        except PeerAreaUnavailable:
            excluded.append({"unit_code": unit["unit_code"], "reason": "net_area_unavailable"})
            continue
        units.append(unit)
    if excluded:
        limitations.append(f"PEER_AREA_UNAVAILABLE:{len(excluded)}")
    keys = [u["unit_key"] for u in units]

    inventory = await run.select(
        "fact_unit_inventory_snapshot",
        f"SELECT * FROM fact_unit_inventory_snapshot WHERE snapshot_date_key = {key} AND unit_key IN {_in(keys)} ORDER BY unit_key",
    )
    diagnostics = await run.select(
        "dm_unit_friction_diagnostics",
        f"SELECT * FROM dm_unit_friction_diagnostics WHERE snapshot_date_key = {key} AND unit_key IN {_in(keys)} ORDER BY unit_key",
    )
    causes = await run.select(
        "unit_diagnostic_causes",
        f"SELECT * FROM unit_diagnostic_causes WHERE snapshot_date_key = {key} AND unit_key IN {_in(keys)}"
        " ORDER BY unit_key, severity_rank",
    )
    projects = await run.select(
        "dim_project_profile",
        f"SELECT * FROM dim_project_profile WHERE project_key IN {_in(u['project_key'] for u in units)} ORDER BY project_key",
    )
    zones = await run.select(
        "dim_zone_master",
        f"SELECT * FROM dim_zone_master WHERE zone_key IN {_in(u['zone_key'] for u in units)} ORDER BY zone_key",
    )
    channel_keys = [r["channel_key"] for r in inventory if r["channel_key"] is not None]
    channels = await run.select(
        "dim_sales_channel",
        f"SELECT * FROM dim_sales_channel WHERE channel_key IN {_in(channel_keys)} ORDER BY channel_key",
    )
    coverage, leads = await _funnel(run, [subject["unit_key"]])

    dataset_limits = [*limitations, "SYNTHETIC_SOURCE:net_area_m2"]  # B-3: mock value = area_m2 × 0.92
    if projects:
        dataset_limits.append("BLOCKED:D2b_segment_mapping")  # raw DW segment kept; no enum mapping
    dataset = {
        "snapshot": _snapshot_block(run),
        "population": {"rule": spec.population, "subject_unit_key": subject["unit_key"],
                       "candidate_filter": {"unit_type": subject["unit_type"]} if spec.population == "peer_candidates" else {},
                       "area_field": PEER_AREA_FIELD},
        "tables": {"dim_project_profile": projects, "dim_zone_master": zones, "dim_unit_master": units,
                   "fact_unit_inventory_snapshot": inventory, "dm_unit_friction_diagnostics": diagnostics,
                   "unit_diagnostic_causes": causes, "dim_sales_channel": channels},
        "row_counts": {"dim_unit_master": len(units), "fact_unit_inventory_snapshot": len(inventory),
                       "dm_unit_friction_diagnostics": len(diagnostics), "unit_diagnostic_causes": len(causes)},
        "excluded": excluded,
        "semantic_config": config,
        "queries": run.queries,
    }
    dataset_ref, _ = await run.put(ArtifactType.DATASET, "re_dataset@1", dataset, dataset_limits, partial=bool(excluded))

    inv = next((r for r in inventory if r["unit_key"] == subject["unit_key"]), None)
    diag = next((r for r in diagnostics if r["unit_key"] == subject["unit_key"]), None)
    raw: dict[str, Any] = {
        "dom_days": inv and inv["unsold_days_dom"],
        "net_price_per_m2_vnd": inv and inv["net_price_per_m2"],
        "asking_price_vnd": inv and inv["asking_price_vnd"],
        "net_area_m2": str(peer_area(subject)),
        "inquiry_leads_30d": leads.get(subject["unit_key"]),
        "subsidy_duration_mo": diag and diag["subsidy_duration_mo"],
        "dw_peer_n": diag and diag["peer_n"],
        "discount_pct": None,
    }
    metric_limits: list[str] = []
    rows = []
    for metric_id in UNIT_METRICS:
        value = raw[metric_id]
        if value is None:
            metric_limits.append(_null_reason(metric_id, coverage))
        definition = METRICS[metric_id]
        rows.append({"metric_id": metric_id, "calculation_ref": definition.calculation_ref,
                     "subject": {"type": "UNIT", "id": subject["unit_key"], "label": subject["unit_code"]},
                     "value": value, "unit": definition.unit,
                     "source_ref": f"re:{definition.source}" if definition.source else None})
    metric_ref, _ = await run.put(ArtifactType.METRIC, "re_metric@1", {"metrics": rows}, metric_limits, [dataset_ref],
                                  partial=bool(metric_limits))

    dq, dq_limits = _dq(run, considered, inventory, coverage)
    dq_ref, _ = await run.put(ArtifactType.DQ, "re_dq@1", dq, dq_limits, [dataset_ref], partial=dq["overall_status"] != "VALID")

    warnings = [*dataset_limits, *metric_limits, *dq_limits]
    summary = (f"{subject['unit_code']} @ {run.snapshot_id}: {len(units)} căn trong tập dữ liệu"
               f" ({'ứng viên cùng loại căn' if spec.population == 'peer_candidates' else 'chỉ căn mục tiêu'}),"
               f" {len(warnings)} hạn chế.")
    return _report(run.step, "completed", refs=[dataset_ref, metric_ref, dq_ref], warnings=warnings,
                   partial=bool(excluded or metric_limits or dq_limits), summary=summary)


def _null_reason(metric_id: str, coverage: dict[str, Any]) -> str:
    if metric_id == "inquiry_leads_30d" and not coverage["complete"]:
        return f"WINDOW_INCOMPLETE:inquiry_leads_30d:{coverage['days_covered']}"
    return f"METRIC_UNAVAILABLE:{metric_id}"


async def _funnel(run: _Run, unit_keys: Sequence[str]) -> tuple[dict[str, Any], dict[str, int]]:
    """30-day lead coverage ending at the snapshot date; leads are summed only over a complete window (B-4)."""
    end = run.snapshot_date_key
    start = _date_key(_day(end) - timedelta(days=FUNNEL_WINDOW_DAYS - 1))
    rows = await run.select(
        "fact_sales_funnel_daily",
        "SELECT MIN(date_key) AS min_date_key, MAX(date_key) AS max_date_key, COUNT(DISTINCT date_key) AS days"
        f" FROM fact_sales_funnel_daily WHERE date_key BETWEEN {start} AND {end}",
    )
    days = rows[0]["days"] if rows else 0
    coverage = {"min_date_key": rows[0]["min_date_key"] if rows else None, "max_date_key": rows[0]["max_date_key"] if rows else None,
                "days_covered": days, "days_required": FUNNEL_WINDOW_DAYS, "complete": days == FUNNEL_WINDOW_DAYS}
    if not coverage["complete"]:
        return coverage, {}
    sums = await run.select(
        "fact_sales_funnel_daily",
        f"SELECT unit_key, SUM(leads) AS leads FROM fact_sales_funnel_daily WHERE date_key BETWEEN {start} AND {end}"
        f" AND unit_key IN {_in(unit_keys)} GROUP BY unit_key",
    )
    return coverage, {r["unit_key"]: r["leads"] for r in sums}  # a unit without rows stays null


def _snapshot_block(run: _Run) -> dict[str, Any]:
    return {"snapshot_id": run.snapshot_id, "snapshot_date": _day(run.snapshot_date_key).isoformat(),
            "snapshot_date_key": run.snapshot_date_key, "semantic_config_version": run.semantic}


def _dq(run: _Run, units: Sequence[dict[str, Any]], inventory: Sequence[dict[str, Any]],
        coverage: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    by_unit = {r["unit_key"]: r for r in inventory}
    total = len(units)

    def missing_area(u: dict[str, Any]) -> bool:
        try:
            peer_area(u)
        except PeerAreaUnavailable:
            return True
        return False

    checks = {
        "net_area_m2": sum(1 for u in units if missing_area(u)),
        "inventory_row": sum(1 for u in units if u["unit_key"] not in by_unit),
        "net_price_per_m2": sum(1 for u in units if (by_unit.get(u["unit_key"]) or {}).get("net_price_per_m2") is None),
        "asking_price_vnd": sum(1 for u in units if (by_unit.get(u["unit_key"]) or {}).get("asking_price_vnd") is None),
        "unsold_days_dom": sum(1 for u in units if (by_unit.get(u["unit_key"]) or {}).get("unsold_days_dom") is None),
    }
    fields = [{"field": name, "missing_count": n, "total": total, "missing_pct": _pct(n, total),
               "status": "VALID" if n == 0 else "PARTIAL"} for name, n in checks.items()]
    limitations = [f"DQ_MISSING:{f['field']}:{f['missing_count']}" for f in fields if f["missing_count"]]
    if not coverage["complete"]:
        limitations.append(f"WINDOW_INCOMPLETE:inquiry_leads_30d:{coverage['days_covered']}")
    dq = {"overall_status": "PARTIAL" if limitations else "VALID", "snapshot_date": _day(run.snapshot_date_key).isoformat(),
          "data_as_of": run.loaded_at, "fields": fields, "coverage": {"fact_sales_funnel_daily": coverage}}
    return dq, limitations


# ---- aggregate_metrics -------------------------------------------------------------------------------------------


async def _aggregate(run: _Run, spec: AggregateSpec, config: dict[str, Any], limitations: list[str]) -> AgentReport:
    key = run.snapshot_date_key
    where = [f"i.snapshot_date_key = {key}"]
    for column, value in sorted(spec.filters.items()):
        alias = "i" if column == "inventory_status" else "u"
        where.append(f"{alias}.{column} = {_q(value)}")
    units = await run.select(
        "dim_unit_master",
        "SELECT u.unit_key, u.unit_code, u.project_key, u.zone_key, u.unit_type, u.floor_band, u.launch_batch_id,"
        " u.net_area_m2, u.area_m2, i.inventory_status, i.unsold_days_dom, i.net_price_per_m2, i.asking_price_vnd"
        " FROM dim_unit_master u JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key"
        f" WHERE {' AND '.join(where)} ORDER BY u.unit_key",
    )
    if "re:fact_unit_inventory_snapshot" not in run.sources:
        run.sources.append("re:fact_unit_inventory_snapshot")
    if not units:
        raise StepError("failed", "EMPTY_POPULATION", "no unit in your authorized scope matches the filters")

    dataset = {
        "snapshot": _snapshot_block(run),
        "population": {"rule": "filters", "filters": dict(sorted(spec.filters.items())), "area_field": PEER_AREA_FIELD},
        "tables": {"unit_inventory": units},
        "row_counts": {"unit_inventory": len(units)},
        "excluded": [],
        "semantic_config": config,
        "queries": run.queries,
    }
    dataset_limits = [*limitations, "SYNTHETIC_SOURCE:net_area_m2"]
    dataset_ref, _ = await run.put(ArtifactType.DATASET, "re_dataset@1", dataset, dataset_limits)

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for unit in units:
        groups.setdefault(tuple(str(unit[c]) for c in spec.group_by), []).append(unit)
    column = {"dom_days": "unsold_days_dom", "net_price_per_m2_vnd": "net_price_per_m2", "asking_price_vnd": "asking_price_vnd"}
    metric_limits: list[str] = []
    rows = []
    for metric_id in spec.metrics:
        definition = METRICS[metric_id]
        if metric_id not in AGGREGATABLE:
            metric_limits.append(f"METRIC_UNAVAILABLE:{metric_id}")
        for group_key, members in sorted(groups.items()):
            values: list[Decimal] = []
            if metric_id == "net_area_m2":
                for m in members:
                    try:
                        values.append(peer_area(m))
                    except PeerAreaUnavailable:
                        continue
            elif metric_id in column:
                values = [Decimal(m[column[metric_id]]) for m in members if m[column[metric_id]] is not None]
            subject = ({"type": "POPULATION", "id": "all", "label": "all"} if not spec.group_by else
                       {"type": "GROUP", "id": "|".join(f"{c}={v}" for c, v in zip(spec.group_by, group_key, strict=True)),
                        "label": " / ".join(group_key)})
            rows.append({"metric_id": metric_id, "calculation_ref": definition.calculation_ref, "subject": subject,
                         "statistic": "median", "value": str(percentile_inc(values, Decimal("0.5"))) if values else None,
                         "n": len(values), "unit": definition.unit,
                         "source_ref": f"re:{definition.source}" if definition.source else None})
            if metric_id in AGGREGATABLE and len(values) < len(members):
                metric_limits.append(f"DQ_MISSING:{metric_id}:{len(members) - len(values)}")
    metric_ref, _ = await run.put(ArtifactType.METRIC, "re_metric@1", {"metrics": rows}, metric_limits, [dataset_ref],
                                  partial=bool(metric_limits))
    dq, dq_limits = _dq(run, units, units, {"complete": True, "days_covered": None})
    dq["coverage"] = {}
    dq_ref, _ = await run.put(ArtifactType.DQ, "re_dq@1", dq, dq_limits, [dataset_ref], partial=bool(dq_limits))
    warnings = [*dataset_limits, *metric_limits, *dq_limits]
    return _report(run.step, "completed", refs=[dataset_ref, metric_ref, dq_ref], warnings=warnings,
                   partial=bool(metric_limits or dq_limits),
                   summary=f"{len(units)} căn, {len(groups)} nhóm, {len(spec.metrics)} chỉ số @ {run.snapshot_id}.")
