"""The v1.0 operations of the Data agent: `fetch_units` and `aggregate_metrics` over entities, scope and filters.

A step of the contract (contract_agent.md, tab Data) names *what* it wants (`entities` with a level hint, or `scope_all`;
`filters`, `attributes`, `metrics`, `group_by` from the vocabulary) and never a table, a column, a threshold or a snapshot.
Data does the rest deterministically, no LLM:

S0  check the form and the vocabulary, the caller, and lock the snapshot (the newest APPROVED one when the step has none;
    the semantic version is read from that snapshot's manifest, never from the message)
S1  turn every mention into exactly one entity with the ladder of SPEC §2.4, or ask (QUESTION) / report it out of scope
S2+ read the tables for the population (entities ∩ filters ∩ the caller's scope) at the locked snapshot
S6  check the data and compute the metrics (numerator, denominator, n)
S7  store the artifacts (`dataset`, `metric`, `dq`) and report

A single unit named without filters is served by the same code as the older `subject_unit_code` step, so its answer has the
shape Insight and Compare already read. `run_step_v1` never raises: every failure is a structured `AgentReport`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vdagent_contracts.canonical import percentile_inc
from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.peer_rules import PEER_AREA_FIELD, PeerAreaUnavailable, peer_area
from vdagent_contracts.reports import AgentReport, QuestionOption, ReportError, ReportQuestion
from vdagent_data import steps as core
from vdagent_data import vocab
from vdagent_data.resolve import Candidate, Resolved, Unresolved, name_form, resolve_entities
from vdagent_data.trace import Observer, Tracer

log = logging.getLogger(__name__)

OPERATIONS = ("fetch_units", "aggregate_metrics")
_SPEC = ConfigDict(extra="forbid", frozen=True)

# internal code → (the contract's code, its class): the table D of contract_agent.md, tab Data. Unknown codes are FATAL
# for the Orchestrator, so every code this agent raises is listed here (test_wire asserts it).
ERROR_TABLE: dict[str, tuple[str, ErrorClass]] = {
    "INVALID_STEPSPEC": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "UNSUPPORTED_CONTRACT": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "UNKNOWN_OPERATION": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "INVALID_SPEC": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "UNKNOWN_METRIC": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "SNAPSHOT_REQUIRED": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "SEMANTIC_VERSION_REQUIRED": ("SPEC_INVALID", ErrorClass.SPEC_ISSUE),
    "SNAPSHOT_UNKNOWN": ("DQ_BLOCKING", ErrorClass.DATA_QUALITY),
    "SNAPSHOT_NOT_APPROVED": ("DQ_BLOCKING", ErrorClass.DATA_QUALITY),
    "SEMANTIC_VERSION_MISMATCH": ("DQ_BLOCKING", ErrorClass.DATA_QUALITY),
    "NO_APPROVED_SNAPSHOT": ("DQ_BLOCKING", ErrorClass.DATA_QUALITY),
    "USER_CONTEXT_MISMATCH": ("OUT_OF_SCOPE", ErrorClass.NO_ACCESS),
    "OUT_OF_SCOPE": ("OUT_OF_SCOPE", ErrorClass.NO_ACCESS),
    "UNIT_NOT_FOUND": ("OUT_OF_SCOPE", ErrorClass.NO_ACCESS),
    "EMPTY_POPULATION": ("EMPTY_RESULT", ErrorClass.NO_DATA),
    "SUBJECT_AREA_UNAVAILABLE": ("DATA_UNAVAILABLE", ErrorClass.NO_DATA),
    "RESULT_TRUNCATED": ("RESULT_TRUNCATED", ErrorClass.SPEC_ISSUE),
    "CONFIG_MISSING": ("CONFIG_MISSING", ErrorClass.FATAL),
    "ID_CONFLICT": ("ID_CONFLICT", ErrorClass.FATAL),
    "TOOL_FAILED": ("WORKER_LOST", ErrorClass.TRANSIENT),
    "INTERNAL_ERROR": ("INTERNAL_ERROR", ErrorClass.FATAL),  # not in the contract's table: FATAL by the Orchestrator's rule
}


# ---- what the step may say ---------------------------------------------------------------------------------------------------


class EntityRef(BaseModel):
    model_config = _SPEC

    mention: str = Field(min_length=1, max_length=200)
    kind_hint: Literal["PROJECT", "ZONE", "UNIT", "UNKNOWN"]


class Criteria(BaseModel):
    model_config = _SPEC

    allow_empty: bool = False


class _Spec(BaseModel):
    model_config = _SPEC

    entities: list[EntityRef] = Field(default_factory=list)
    scope_all: bool = False
    out_of_catalog_need: str | None = Field(default=None, max_length=1000)
    success_criteria: Criteria = Field(default_factory=Criteria)

    @model_validator(mode="after")
    def _one_way_to_name_the_population(self) -> _Spec:
        if bool(self.entities) == self.scope_all:
            raise ValueError("exactly one of `entities` (at least one) and `scope_all` (true)")
        return self


class FetchUnitsV1(_Spec):
    filters: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)


class AggregateV1(_Spec):
    metrics: list[str] = Field(min_length=1)
    group_by: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)


def parse_spec(step: StepSpec) -> FetchUnitsV1 | AggregateV1:
    model = {"fetch_units": FetchUnitsV1, "aggregate_metrics": AggregateV1}.get(step.operation)
    if model is None:
        raise core.StepError("rejected", "UNKNOWN_OPERATION", f"unknown operation {step.operation!r}; this agent serves {', '.join(OPERATIONS)}")
    try:
        spec = model.model_validate(step.spec)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "spec"
        raise core.StepError("rejected", "INVALID_SPEC", f"invalid {step.operation} spec at `{where}`: {first['msg']}") from None
    bad = vocab.unknown_names("filter", spec.filters, vocab.FILTERS)
    if isinstance(spec, FetchUnitsV1):
        bad += vocab.unknown_names("attribute", spec.attributes, vocab.ATTRIBUTES)
    else:
        bad += vocab.unknown_names("metric", spec.metrics, vocab.METRICS_V1) + vocab.unknown_names("dimension", spec.group_by, vocab.DIMENSIONS)
    if bad:
        raise core.StepError("rejected", "INVALID_SPEC", "not in the vocabulary of this agent: " + ", ".join(bad))
    for names in ([spec.filters] if isinstance(spec, FetchUnitsV1) else [spec.filters, spec.metrics, spec.group_by]):
        if len(set(names)) != len(names):
            raise core.StepError("rejected", "INVALID_SPEC", "a name is listed twice")
    return spec


# ---- the result --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    kind: str
    name: str


@dataclass(frozen=True)
class Question:
    reason_code: Literal["AMBIGUOUS_REQUEST", "ENTITY_NOT_FOUND"]
    mention: str
    text: str
    options: list[Option]


@dataclass
class V1Result:
    report: AgentReport
    question: Question | None = None
    resolved: list[dict[str, str]] = field(default_factory=list)
    operation: str = ""
    error_note: str = ""


class Ask(core.StepError):
    """The ladder needs the user: carries the closed choices."""

    def __init__(self, unresolved: Unresolved, question: Question) -> None:
        legacy = ReportQuestion(text=question.text, options=[QuestionOption(id=o.id, label=o.label) for o in question.options])
        super().__init__("failed", unresolved.code, unresolved.message, legacy)
        self.v1 = question


def _label(c: Candidate, projects: Mapping[str, str]) -> str:
    kind = {"UNIT": "Căn", "ZONE": "Phân khu", "PROJECT": "Dự án"}[c.kind]
    parent = projects.get(c.project_key)
    return f"{kind} {c.label}" + (f" ({parent})" if parent and c.kind != "PROJECT" else "")


# ---- entry point -------------------------------------------------------------------------------------------------------------


async def run_step_v1(step: StepSpec, tools: core.Tools, observer: Observer | None = None, *, profile: str = "mock",
                      saved: Mapping[str, str] | None = None) -> V1Result:
    """Answer one v1.0 step. `profile` is what the warehouse is ("mock" or "real", DATA_DW_PROFILE); `saved` holds the
    choices the user already made in this run (normalized mention → entity id)."""
    tracer = Tracer(observer)
    run = core._Run(step, tools, trace=tracer)
    run.profile = profile
    out = V1Result(report=core._report(step, "failed", error=ReportError(code="INTERNAL_ERROR", message="not run")), operation=step.operation)
    try:
        out = await _run(run, step, tracer, saved or {}, out)
    except Ask as exc:
        out.report, out.question = core._report(_pinned(run, step), "input_required", question=exc.question), exc.v1
    except core.StepError as exc:
        out.report = core._report(_pinned(run, step), exc.state, error=ReportError(code=exc.code, message=exc.message))
    except core.ToolFailure as exc:
        out.report = core._report(_pinned(run, step), "failed", error=ReportError(code="TOOL_FAILED", message=str(exc), retryable=True))
    except Exception as exc:  # a bug: reported, never raised into the Backend turn
        log.exception("data: v1 step %s failed", step.idempotency_key)
        out.report = core._report(_pinned(run, step), "failed", error=ReportError(code="INTERNAL_ERROR", message=type(exc).__name__))
    await core._finish(tracer, out.report)
    return out


def _pinned(run: core._Run, step: StepSpec) -> StepSpec:
    """The step with the snapshot and semantic version Data locked, once it has locked them."""
    if run.snapshot_id:
        return step.model_copy(update={"snapshot_id": run.snapshot_id, "semantic_config_version": run.semantic})
    return step


async def _run(run: core._Run, step: StepSpec, tracer: Tracer, saved: Mapping[str, str], out: V1Result) -> V1Result:
    tracer.enter("intake")
    await tracer.note("intake", "Nhận phiếu giao việc và kiểm tra khuôn, từ vựng trước khi đọc kho dữ liệu", operation=step.operation,
                      original_question=step.original_question, snapshot_id=step.snapshot_id,
                      spec_entities=[e.get("mention") for e in step.spec.get("entities", []) if isinstance(e, dict)],
                      spec_scope_all=step.spec.get("scope_all", False), spec_filters=step.spec.get("filters", []),
                      spec_metrics=step.spec.get("metrics", []), spec_group_by=step.spec.get("group_by", []))
    spec = parse_spec(step)
    caller = await run.tools.call("get_user_context", {})
    if caller.get("user_id") != step.user_context.user_id:
        raise core.StepError("rejected", "USER_CONTEXT_MISMATCH", "the step's user_context is not the calling user")
    scope = caller.get("authorized_scope") or {}
    await tracer.note("scope", "Lấy phạm vi quyền từ Backend; quyền ghi trong phiếu không được dùng",
                      project_ids=scope.get("project_ids", []), zone_ids=scope.get("zone_ids", []))

    tracer.enter("snapshot")
    await _lock_snapshot(run, step.snapshot_id)
    run.step = _pinned(run, step)
    await tracer.note("snapshot", "Khóa kỳ chốt dữ liệu đã duyệt cho cả bước, không dùng bản nháp",
                      snapshot_id=run.snapshot_id, snapshot_date=core._day(run.snapshot_date_key).isoformat(),
                      semantic_config_version=run.semantic, locked_by_agent=step.snapshot_id is None)
    config, config_limits = await core._semantic_config(run)
    await tracer.note("config", "Đọc ngưỡng nghiệp vụ từ cấu hình của kho; ngưỡng chưa duyệt được nêu rõ, không dùng mặc định",
                      approved=[k for k, v in config.items() if v["status"] == "APPROVED"],
                      pending=[k for k, v in config.items() if v["status"] != "APPROVED"],
                      missing=[k for k in core.CONFIG_KEYS if k not in config])
    _require_thresholds(spec, config)

    tracer.enter("resolve")
    resolved = await _resolve(run, spec, step, saved)
    out.resolved = [{"mention": r.mention, "kind": r.candidate.kind, "id": r.candidate.key, "name": r.candidate.label, "method": r.method}
                    for r in resolved]
    if resolved:
        await tracer.note("resolve", "Đã nhận diện đối tượng người dùng nêu, không đoán và không dùng LLM",
                          entities=[f"{r.mention} → {r.candidate.kind} {r.candidate.label} ({r.method})" for r in resolved])
    limitations = [*config_limits, *core._source_labels(run)]
    if spec.out_of_catalog_need:
        limitations.append("OUT_OF_CATALOG_NEED_NOT_SERVED")  # no T3 in this build: the catalog part is served, the rest is said
    pop = Population(resolved, list(spec.filters), run.snapshot_date_key, _threshold(config))
    if isinstance(spec, FetchUnitsV1):
        single = len(resolved) == 1 and resolved[0].candidate.kind == "UNIT" and not spec.scope_all and not spec.filters
        if single:
            out.report = await _single_unit(run, resolved[0].candidate, config, limitations)
        else:
            out.report = await _unit_set(run, spec, pop, config, limitations)
    else:
        out.report = await _aggregate(run, spec, pop, config, limitations)
    return out


# ---- S0: the snapshot --------------------------------------------------------------------------------------------------------


async def _lock_snapshot(run: core._Run, requested: str | None) -> None:
    if requested is not None and not core._IDENT.fullmatch(requested):
        raise core.StepError("rejected", "SNAPSHOT_UNKNOWN", f"unknown snapshot {requested!r}")
    rows = await run.select("snapshot_manifest", "SELECT * FROM snapshot_manifest ORDER BY snapshot_date_key DESC",
                            "Đọc các kỳ chốt của kho để khóa kỳ chốt cho cả bước (kỳ mới nhất đã duyệt nếu phiếu chưa chỉ định)")
    approved_versions = {r["config_version"] for r in await run.select(
        "semantic_config", "SELECT DISTINCT config_version FROM semantic_config WHERE status = 'APPROVED'",
        "Xem phiên bản cấu hình ngưỡng nào đã có dòng được duyệt")}

    def status(row: dict[str, Any]) -> str:
        return str(row.get("status") or "APPROVED")

    if requested is not None:
        row = next((r for r in rows if r["snapshot_id"] == requested), None)
        if row is None:
            raise core.StepError("rejected", "SNAPSHOT_UNKNOWN", f"unknown snapshot {requested!r}")
        if status(row) != "APPROVED":
            raise core.StepError("rejected", "SNAPSHOT_NOT_APPROVED", f"snapshot {requested} is {status(row)}; only APPROVED snapshots are served")
    else:
        row = next((r for r in rows if status(r) == "APPROVED" and r["semantic_config_version"] in approved_versions), None)
        if row is None:
            raise core.StepError("failed", "NO_APPROVED_SNAPSHOT", "the warehouse has no APPROVED snapshot with an approved semantic config")
    run.snapshot_id, run.semantic = row["snapshot_id"], row["semantic_config_version"]
    run.snapshot_date_key, run.loaded_at = row["snapshot_date_key"], str(row.get("loaded_at") or "")


def _threshold(config: Mapping[str, Any]) -> int | None:
    entry = config.get("overdue_threshold_days")
    return int(entry["value"]) if entry and entry["status"] == "APPROVED" else None


def _require_thresholds(spec: FetchUnitsV1 | AggregateV1, config: Mapping[str, Any]) -> None:
    needs: list[str] = []
    if "slow_moving" in spec.filters:
        needs.append("overdue_threshold_days")
    if isinstance(spec, AggregateV1):
        needs += [k for m in spec.metrics if (k := vocab.METRICS_V1[m].needs)]
    for key in dict.fromkeys(needs):
        if key not in config or config[key]["status"] != "APPROVED":
            raise core.StepError("failed", "CONFIG_MISSING", f"threshold `{key}` is missing or not approved in semantic_config; no default is used")


# ---- S1: the entities --------------------------------------------------------------------------------------------------------


async def _resolve(run: core._Run, spec: FetchUnitsV1 | AggregateV1, step: StepSpec, saved: Mapping[str, str]) -> list[Resolved]:
    if spec.scope_all:
        return []
    try:
        return await resolve_entities(run.select, [(e.mention, e.kind_hint) for e in spec.entities], step.original_question, saved)
    except Unresolved as exc:
        if exc.code == "OUT_OF_SCOPE":
            raise core.StepError("rejected", "OUT_OF_SCOPE", exc.message) from None
        projects = {str(r["project_key"]): r["project_name"] for r in await run.select(
            "dim_project_profile", "SELECT project_key, project_name FROM dim_project_profile", "Lấy tên dự án để ghi rõ dự án cha của từng lựa chọn")}
        options = [Option(c.key, _label(c, projects), c.kind, c.label) for c in exc.options][:10]
        raise Ask(exc, Question(exc.code, exc.mention, exc.message, options)) from None  # type: ignore[arg-type]


# ---- the population ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Population:
    resolved: Sequence[Resolved]
    filters: Sequence[str]
    snapshot_key: int
    threshold: int | None

    @property
    def base(self) -> str:
        return (f"dim_unit_master u JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key"
                f" AND i.snapshot_date_key = {self.snapshot_key}")

    @property
    def where(self) -> str:
        parts = []
        for column, kind in (("u.unit_key", "UNIT"), ("u.zone_key", "ZONE"), ("u.project_key", "PROJECT")):
            keys = [r.candidate.key for r in self.resolved if r.candidate.kind == kind]
            if keys:
                parts.append(f"{column} IN {core._in(keys)}")
        clauses = ["(" + " OR ".join(parts) + ")"] if parts else ["1 = 1"]
        for name in self.filters:
            if name in vocab.STATUS_OF_FILTER:
                clauses.append(f"i.inventory_status = '{vocab.STATUS_OF_FILTER[name]}'")
            elif name == "slow_moving":
                assert self.threshold is not None  # _require_thresholds
                clauses.append(f"i.inventory_status = 'AVAILABLE' AND i.unsold_days_dom > {self.threshold}")
            # "released": every row of the inventory snapshot is a released unit, so it adds no condition
        return " AND ".join(clauses)

    def via_units(self, table: str, alias: str, *, dated: bool = True) -> str:
        """`table` rows (keyed by unit) of this population."""
        key = f" AND {alias}.snapshot_date_key = {self.snapshot_key}" if dated else ""
        return (f"SELECT {alias}.* FROM {table} {alias} JOIN dim_unit_master u ON u.unit_key = {alias}.unit_key"
                f" JOIN fact_unit_inventory_snapshot i ON i.unit_key = u.unit_key AND i.snapshot_date_key = {self.snapshot_key}"
                f" WHERE {self.where}{key}")


def _describe(pop: Population) -> str:
    if not pop.resolved:
        who = "toàn bộ phạm vi quyền của người dùng"
    else:
        who = ", ".join(f"{r.candidate.kind.lower()} {r.candidate.label}" for r in pop.resolved)
    return who + (f", lọc {', '.join(pop.filters)}" if pop.filters else "")


# ---- fetch_units -------------------------------------------------------------------------------------------------------------


async def _single_unit(run: core._Run, unit: Candidate, config: dict[str, Any], limitations: list[str]) -> AgentReport:
    """One unit and nothing else: the same code, so the same answer, as the `subject_unit_code` step."""
    spec = core.FetchUnitsSpec(subject_unit_code=unit.code, population="subject", project_ids=[unit.project_key])
    report = await core._fetch_units(run, spec, config, [*limitations])
    extra = [w for w in limitations if w not in report.warnings and w.startswith("OUT_OF_CATALOG")]
    return report.model_copy(update={"warnings": sorted({*report.warnings, *extra})}) if extra else report


async def _unit_set(run: core._Run, spec: FetchUnitsV1, pop: Population, config: dict[str, Any], limitations: list[str]) -> AgentReport:
    run.trace.enter("fetch")
    units = await run.select("dim_unit_master", f"SELECT u.* FROM {pop.base} WHERE {pop.where} ORDER BY u.unit_key",
                             f"Lấy các căn của {_describe(pop)} ở kỳ chốt đã khóa")
    if not units and not spec.success_criteria.allow_empty:
        raise core.StepError("failed", "EMPTY_POPULATION", f"no unit of {_describe(pop)} in your authorized scope")
    inventory = await run.select("fact_unit_inventory_snapshot", f"SELECT i.* FROM {pop.base} WHERE {pop.where} ORDER BY i.unit_key",
                                 "Lấy dòng tồn kho của các căn đó (trạng thái, số ngày tồn, giá)")
    diagnostics = await run.select("dm_unit_friction_diagnostics", f"{pop.via_units('dm_unit_friction_diagnostics', 'd')} ORDER BY d.unit_key",
                                   "Lấy chẩn đoán ma sát bán hàng của các căn đó ở kỳ chốt")
    causes = await run.select("unit_diagnostic_causes", f"{pop.via_units('unit_diagnostic_causes', 'c')} ORDER BY c.unit_key, c.severity_rank",
                              "Lấy các nguyên nhân được chẩn đoán và mức độ của từng nguyên nhân")
    projects = await run.select("dim_project_profile", f"SELECT * FROM dim_project_profile WHERE project_key IN {core._in(str(u['project_key']) for u in units)}"
                                " ORDER BY project_key", "Lấy hồ sơ dự án của các căn đã đọc")
    zones = await run.select("dim_zone_master", f"SELECT * FROM dim_zone_master WHERE zone_key IN {core._in(str(u['zone_key']) for u in units)}"
                             " ORDER BY zone_key", "Lấy thông tin phân khu của các căn đã đọc")
    channel_keys = sorted({str(r["channel_key"]) for r in inventory if r.get("channel_key") is not None})
    channels = await run.select("dim_sales_channel", f"SELECT * FROM dim_sales_channel WHERE channel_key IN {core._in(channel_keys)} ORDER BY channel_key",
                                "Lấy kênh bán của các dòng tồn kho đã đọc")
    run.trace.enter("check")
    dq, dq_limits = core._dq(run, units, inventory, {"complete": True, "days_covered": None})
    dq["coverage"] = {}
    await core._check_note(run, dq, dq_limits)

    if not units:
        limitations.append("EMPTY_RESULT")
    if projects:
        limitations += core._project_labels(run)
    dataset = {
        "snapshot": core._snapshot_block(run),
        "population": {"rule": "entities", "subject_unit_key": None, "entities": [_entity(r) for r in pop.resolved], "scope_all": not pop.resolved,
                       "filters": list(pop.filters), "attributes": list(spec.attributes), "area_field": PEER_AREA_FIELD},
        "tables": {"dim_project_profile": projects, "dim_zone_master": zones, "dim_unit_master": units,
                   "fact_unit_inventory_snapshot": inventory, "dm_unit_friction_diagnostics": diagnostics,
                   "unit_diagnostic_causes": causes, "dim_sales_channel": channels},
        "row_counts": {"dim_unit_master": len(units), "fact_unit_inventory_snapshot": len(inventory),
                       "dm_unit_friction_diagnostics": len(diagnostics), "unit_diagnostic_causes": len(causes)},
        "excluded": [], "semantic_config": config, "queries": run.queries,
    }
    dataset_ref, _ = await run.put(ArtifactType.DATASET, "re_dataset@1", dataset, limitations)
    members = _merge(units, inventory)
    names = [m for m in vocab.SET_SUMMARY_METRICS if m != "slow_moving_count" or pop.threshold is not None]
    rows, metric_limits = _measure(names, {(): members}, [], pop.threshold, {})
    metric_ref, _ = await run.put(ArtifactType.METRIC, "re_metric@1", {"metrics": rows}, metric_limits, [dataset_ref], partial=bool(metric_limits))
    dq_ref, _ = await run.put(ArtifactType.DQ, "re_dq@1", dq, dq_limits, [dataset_ref], partial=bool(dq_limits))
    warnings = [*limitations, *metric_limits, *dq_limits]
    summary = f"{len(units)} căn của {_describe(pop)} @ {run.snapshot_id}, {len(warnings)} hạn chế."
    return core._report(run.step, "completed", refs=[dataset_ref, metric_ref, dq_ref], warnings=warnings,
                        partial=bool(metric_limits or dq_limits), summary=summary)


def _entity(r: Resolved) -> dict[str, str]:
    return {"mention": r.mention, "kind": r.candidate.kind, "id": r.candidate.key, "name": r.candidate.label, "method": r.method}


def _merge(units: Sequence[dict[str, Any]], inventory: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_unit = {r["unit_key"]: r for r in inventory}
    return [{**u, **by_unit.get(u["unit_key"], {})} for u in units]


# ---- aggregate_metrics -------------------------------------------------------------------------------------------------------


def _dec(value: Any) -> Decimal | None:
    return None if value is None or value == "" else Decimal(str(value))


def _q2(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _column_values(members: Sequence[dict[str, Any]], column: str) -> list[Decimal]:
    return [d for m in members if (d := _dec(m.get(column))) is not None]


def _measure_one(metric_id: str, members: Sequence[dict[str, Any]], threshold: int | None) -> tuple[Any, int, int | None, int | None]:
    """(value, n, numerator, denominator) of one metric over one group."""
    available = [m for m in members if m.get("inventory_status") == "AVAILABLE"]
    slow = [m for m in available if (d := _dec(m.get("unsold_days_dom"))) is not None and threshold is not None and d > threshold]
    if metric_id == "unit_count":
        return len(members), len(members), None, None
    if metric_id == "slow_moving_count":
        return len(slow), len(available), None, None
    if metric_id == "slow_moving_rate":
        return (_q2(Decimal(100 * len(slow)) / len(available)) if available else None), len(available), len(slow), len(available)
    if metric_id == "absorption_rate":
        sold = sum(1 for m in members if m.get("inventory_status") == "SOLD")
        return (_q2(Decimal(100 * sold) / len(members)) if members else None), len(members), sold, len(members)
    if metric_id == "avg_dom_unsold":
        values = _column_values(available, "unsold_days_dom")
        return (_q2(sum(values) / len(values)) if values else None), len(values), None, None
    if metric_id == "avg_net_price_per_m2":
        values = _column_values(members, "net_price_per_m2")
        return (_q2(sum(values) / len(values)) if values else None), len(values), None, None
    if metric_id == "net_area_m2":
        values = []
        for m in members:
            try:
                values.append(peer_area(m))
            except PeerAreaUnavailable:
                continue
    else:
        column = {"dom_days": "unsold_days_dom", "net_price_per_m2_vnd": "net_price_per_m2", "asking_price_vnd": "asking_price_vnd"}.get(metric_id, metric_id)
        values = _column_values(members, column)
    return (str(percentile_inc(values, Decimal("0.5"))) if values else None), len(values), None, None


def _measure(metric_ids: Sequence[str], groups: Mapping[tuple[str, ...], list[dict[str, Any]]], dims: Sequence[str],
             threshold: int | None, fields: Mapping[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    limits: list[str] = []
    columns = [fields[d] for d in dims]
    for metric_id in metric_ids:
        definition = vocab.METRICS_V1[metric_id]
        column = definition.optional_column
        for key, members in sorted(groups.items()):
            if column is not None and not any(column in m for m in members):
                value, n, num, den = None, 0, None, None
                if f"METRIC_UNAVAILABLE:{metric_id}" not in limits:
                    limits.append(f"METRIC_UNAVAILABLE:{metric_id}")  # the warehouse does not carry the column: null, never 0
            else:
                value, n, num, den = _measure_one(metric_id, members, threshold)
                if column is not None and n < len(members):
                    limits.append(f"DQ_MISSING:{metric_id}:{len(members) - n}")
            subject = ({"type": "POPULATION", "id": "all", "label": "all"} if not dims else
                       {"type": "GROUP", "id": "|".join(f"{c}={v}" for c, v in zip(columns, key, strict=True)), "label": " / ".join(key)})
            row: dict[str, Any] = {"metric_id": metric_id, "calculation_ref": definition.calculation_ref, "subject": subject,
                                   "statistic": definition.statistic, "value": value, "n": n, "unit": definition.unit,
                                   "source_ref": f"re:{definition.source}" if definition.source else None,
                                   "status": "provisional" if definition.provisional else "approved"}
            if num is not None:
                row["numerator"], row["denominator"] = num, den
            rows.append(row)
        if definition.provisional:
            limits.append(f"PROVISIONAL_DEFINITION:{metric_id}")
    return rows, sorted(set(limits))


async def _aggregate(run: core._Run, spec: AggregateV1, pop: Population, config: dict[str, Any], limitations: list[str]) -> AgentReport:
    run.trace.enter("fetch")
    units = await run.select("dim_unit_master", f"SELECT u.* FROM {pop.base} WHERE {pop.where} ORDER BY u.unit_key",
                             f"Lấy các căn của {_describe(pop)} ở kỳ chốt đã khóa để tính chỉ số")
    if not units and not spec.success_criteria.allow_empty:
        raise core.StepError("failed", "EMPTY_POPULATION", f"no unit of {_describe(pop)} in your authorized scope")
    inventory = await run.select("fact_unit_inventory_snapshot", f"SELECT i.* FROM {pop.base} WHERE {pop.where} ORDER BY i.unit_key",
                                 "Lấy dòng tồn kho của các căn đó ở kỳ chốt (trạng thái, số ngày tồn, giá)")
    fields = {d: vocab.DIMENSIONS[d] for d in spec.group_by}
    market: dict[str, str] = {}
    if "market" in spec.group_by:
        market = {str(p["project_key"]): str(p["market_id"]) for p in await run.select(
            "dim_project_profile", "SELECT project_key, market_id FROM dim_project_profile", "Lấy thị trường của từng dự án để chia nhóm theo thị trường")}
    members = _merge(units, inventory)
    for m in members:
        m["market_id"] = market.get(str(m["project_key"]), "")
    run.trace.enter("check")
    dq, dq_limits = core._dq(run, units, inventory, {"complete": True, "days_covered": None})
    dq["coverage"] = {}
    await core._check_note(run, dq, dq_limits)

    if not units:
        limitations.append("EMPTY_RESULT")
    narrow = ("unit_key", "unit_code", "project_key", "zone_key", "unit_type", "floor_band", "launch_batch_id", "balcony_orientation",
              "view_primary_type", "net_area_m2", "area_m2", "inventory_status", "unsold_days_dom", "net_price_per_m2", "asking_price_vnd",
              "channel_key", "discount_pct", "subsidy_duration_mo")
    dataset = {
        "snapshot": core._snapshot_block(run),
        "population": {"rule": "entities", "entities": [_entity(r) for r in pop.resolved], "scope_all": not pop.resolved,
                       "filters": list(pop.filters), "area_field": PEER_AREA_FIELD},
        "tables": {"unit_inventory": [{k: m[k] for k in narrow if k in m} | ({"market_id": m["market_id"]} if market else {}) for m in members]},
        "row_counts": {"unit_inventory": len(members)}, "excluded": [], "semantic_config": config, "queries": run.queries,
    }
    dataset_ref, _ = await run.put(ArtifactType.DATASET, "re_dataset@1", dataset, limitations)
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for m in members:
        groups[tuple(str(m.get(fields[d], "")) for d in spec.group_by)].append(m)
    if not groups:
        groups[tuple("" for _ in spec.group_by)] = []
    rows, metric_limits = _measure(spec.metrics, groups, spec.group_by, pop.threshold, fields)
    metric_ref, _ = await run.put(ArtifactType.METRIC, "re_metric@1", {"metrics": rows}, metric_limits, [dataset_ref], partial=bool(metric_limits))
    dq_ref, _ = await run.put(ArtifactType.DQ, "re_dq@1", dq, dq_limits, [dataset_ref], partial=bool(dq_limits))
    warnings = [*limitations, *metric_limits, *dq_limits]
    summary = f"{len(members)} căn của {_describe(pop)}, {len(groups)} nhóm, {len(spec.metrics)} chỉ số @ {run.snapshot_id}."
    return core._report(run.step, "completed", refs=[dataset_ref, metric_ref, dq_ref], warnings=warnings,
                        partial=bool(metric_limits or dq_limits), summary=summary)
