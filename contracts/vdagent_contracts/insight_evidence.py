"""`insight_evidence@2`: the typed evidence an `insight` artifact carries for its consumers (Chart, Report, answer).

Insight builds it from its deterministic candidates, never from its narration: every number a finding stands on, with
its canonical metric id, unit and a JSON pointer into the one Data dataset it was read from. Consumers read only this
block (`payload.evidence`); they never parse `claim.rendered_text` / `display`, and never depend on which slots a
narration happened to mention (an LLM chooses those, so they change from run to run).

- `METRICS`: the canonical metric catalog, keyed by the Data dataset field (`<table>.<field>`): label, unit, and — for
  the DW mart's peer-relative fields — the Compare figure measuring the same thing.
- Ownership: Data owns business facts, Compare owns every peer/comparison fact (an explicit, listed peer set in
  `peer_definition`, the numbers in `comparison`). The mart's peer-relative fields use another, unpublished peer
  set, so @2 forbids them as evidence: a finding that stands on a peer comparison declares a `target_vs_peer` intent
  that `requires: comparison`, and consumers bind it to Compare's row through `comparison_facts` (Insight and Compare
  run in parallel; the binding happens downstream, never by Insight recomputing a peer number).
- `peer_claims` is the defensive check for a narrated peer number (a stale or malformed insight artifact): consumers
  never show such a sentence as is and report `PEER_BASIS_DIFFERS`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from vdagent_contracts.envelope import FROZEN, ArtifactRef, ArtifactType

EVIDENCE_SCHEMA = "insight_evidence@2"
Unit = Literal["DAY", "PCT", "VND", "VND_PER_M2", "RATIO", "COUNT", "SCORE"]


@dataclass(frozen=True)
class PeerCounterpart:
    compare_metric: str  # canonical id of the Compare metric row (its sourceRef `<table>.<column>`)
    field: str  # JSON pointer inside that row, e.g. "/pctGap", "/benchmark/n"


@dataclass(frozen=True)
class MetricDef:
    label: str
    unit: Unit
    peer: PeerCounterpart | None = None  # set: a DW-mart figure relative to the mart's own peer set


_PRICE = "fact_unit_inventory_snapshot.net_price_per_m2"
METRICS: dict[str, MetricDef] = {
    "fact_unit_inventory_snapshot.unsold_days_dom": MetricDef("Thời gian trên thị trường (DOM)", "DAY"),
    _PRICE: MetricDef("Giá ròng/m²", "VND_PER_M2"),
    "dm_unit_friction_diagnostics.physical_defect_penalty": MetricDef("Điểm phạt khuyết tật", "SCORE"),
    "dm_unit_friction_diagnostics.thermal_view_penalty": MetricDef("Điểm phạt nhiệt/hướng", "SCORE"),
    "dm_unit_friction_diagnostics.subsidy_duration_mo": MetricDef("Thời gian hỗ trợ lãi suất (tháng)", "COUNT"),
    "dm_unit_friction_diagnostics.secondary_price_gap_pct": MetricDef("Giá sơ cấp so với thứ cấp", "PCT"),
    "dm_unit_friction_diagnostics.ticket_size_vs_income_ratio": MetricDef("Giá trị căn / thu nhập năm của hộ", "RATIO"),
    "dm_unit_friction_diagnostics.funnel_dropoff_rate_pct": MetricDef("Tỷ lệ rút cọc", "PCT"),
    "dim_sales_channel.base_commission_pct": MetricDef("Hoa hồng sàn", "PCT"),
    "dim_sales_channel.spiff_bonus_vnd": MetricDef("Thưởng thêm cho sàn", "VND"),
    "dm_unit_friction_diagnostics.price_spread_vs_peer_pct": MetricDef(
        "Đơn giá/m² so với trung vị peer (mart DW)", "PCT", PeerCounterpart(_PRICE, "/pctGap")),
    "dm_unit_friction_diagnostics.peer_n": MetricDef(
        "Số căn tương đồng (mart DW)", "COUNT", PeerCounterpart(_PRICE, "/benchmark/n")),
}

PEER_RELATIVE_FIELDS = frozenset({id_.split(".", 1)[1] for id_, d in METRICS.items() if d.peer is not None} | {"peer_count"})
"""Field names of the mart's peer-relative figures (`peer_count` is Insight's local name of `peer_n`)."""


class EvidenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def decimal_of(value: Any) -> Decimal | None:
    """The exact finite decimal of an upstream value (int, decimal string), None for anything else."""
    if value is None or isinstance(value, bool):
        return None
    try:
        exact = Decimal(str(value))
    except InvalidOperation:
        return None
    return exact if exact.is_finite() else None


def same_value(a: Any, b: Any) -> bool:
    """Exact decimal equality ("12.40" == "12.4" == 12.4); never equal when either side is not a number."""
    da, db = decimal_of(a), decimal_of(b)
    return da is not None and db is not None and da == db


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 lookup (`/tables/x/0/field`); raises KeyError / IndexError / ValueError / TypeError."""
    value = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


class Subject(BaseModel):
    model_config = FROZEN

    type: str
    id: str
    label: str


class EvidenceMetric(BaseModel):
    model_config = FROZEN

    metric_id: str  # `<table>.<field>` of the Data dataset (a METRICS key when chartable)
    slot: str  # Insight's slot name for the same number
    label: str
    value_exact: str  # the number exactly as Insight bound it (decimal string)
    unit: Unit
    role: Literal["context", "primary", "supporting"]
    source_ref: str | None  # `<dataset id>@<version>#<pointer>`; None when Insight computed the value
    chartable: bool
    not_chartable_reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> EvidenceMetric:
        if decimal_of(self.value_exact) is None:
            raise ValueError(f"value_exact {self.value_exact!r} is not a finite decimal")
        known = METRICS.get(self.metric_id)
        if known is not None and known.peer is not None:
            raise ValueError(f"{self.metric_id} is a peer fact on the DW mart's own peer set; Compare owns peer facts")
        if not self.chartable:
            if not self.not_chartable_reason:
                raise ValueError("a non-chartable metric must say why (not_chartable_reason)")
            return self
        if self.not_chartable_reason is not None:
            raise ValueError("a chartable metric has no not_chartable_reason")
        if known is None:
            raise ValueError(f"unknown metric id {self.metric_id!r}")
        if (self.unit, self.label) != (known.unit, known.label):
            raise ValueError(f"{self.metric_id} must have unit {known.unit} and label {known.label!r}")
        if self.source_ref is None:
            raise ValueError(f"chartable {self.metric_id} has no source_ref")
        return self


class VisualIntent(BaseModel):
    model_config = FROZEN

    question: Literal["current_value", "target_vs_peer"]
    chart_type: Literal["kpi_card", "bar"]
    metric_ids: list[str] = Field(min_length=1)
    requires: Literal["comparison"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> VisualIntent:
        expected = {"current_value": ("kpi_card", None), "target_vs_peer": ("bar", "comparison")}[self.question]
        if (self.chart_type, self.requires) != expected:
            raise ValueError(f"{self.question} is drawn as {expected[0]!r} and requires {expected[1]!r}")
        return self


class EvidenceFinding(BaseModel):
    model_config = FROZEN

    finding_id: str  # Insight's deterministic candidate id
    insight_id: str | None  # the narrated insight stating it in this run; None when the narration skipped it
    insight_type: str
    cause_code: str | None
    level: str
    subject: Subject
    severity_rank: int | None
    attribution_score: str | None
    confidence: str
    metrics: list[EvidenceMetric]
    visual_intents: list[VisualIntent]
    limitations: list[str]

    @model_validator(mode="after")
    def _intents_point_at_own_chartable_metrics(self) -> EvidenceFinding:
        ids = [m.metric_id for m in self.metrics]
        if len(ids) != len(set(ids)):
            raise ValueError("a metric appears more than once in a finding")
        chartable = {m.metric_id for m in self.metrics if m.chartable}
        for intent in self.visual_intents:
            if intent.question == "current_value" and not set(intent.metric_ids) <= chartable:
                raise ValueError(f"current_value names non-chartable metrics {sorted(set(intent.metric_ids) - chartable)}")
            if intent.question == "target_vs_peer":
                unknown = [i for i in intent.metric_ids if i not in METRICS or METRICS[i].peer is not None]
                if unknown:
                    raise ValueError(f"target_vs_peer names metrics Compare does not measure: {unknown}")
        return self


class CandidatesRef(BaseModel):
    model_config = FROZEN

    artifact_id: str
    content_hash: str


class InsightEvidence(BaseModel):
    model_config = FROZEN

    schema_version: Literal["insight_evidence@2"]
    snapshot_id: str
    semantic_config_version: str
    dataset_ref: ArtifactRef  # the one Data dataset every source_ref points into, pinned by hash
    candidates_ref: CandidatesRef  # Insight's own record of the candidates the findings come from
    findings: list[EvidenceFinding]

    @model_validator(mode="after")
    def _pinned(self) -> InsightEvidence:
        if self.dataset_ref.artifact_type is not ArtifactType.DATASET or self.dataset_ref.content_hash is None:
            raise ValueError("dataset_ref must pin a dataset by content_hash")
        prefix = f"{self.dataset_ref.artifact_id}@{self.dataset_ref.version}#"
        for f in self.findings:
            for m in f.metrics:
                if m.source_ref is not None and not m.source_ref.startswith(prefix):
                    raise ValueError(f"{f.finding_id}/{m.metric_id}: source_ref is not in {prefix[:-1]}")
        ids = [f.finding_id for f in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("finding ids are not unique")
        return self


def parse_evidence(insight_payload: Mapping[str, Any]) -> InsightEvidence:
    """The `evidence` block of an insight artifact's payload; `EvidenceError` when missing or not the contract."""
    raw = insight_payload.get("evidence")
    if raw is None:
        raise EvidenceError("INSIGHT_EVIDENCE_MISSING", f"the insight artifact has no {EVIDENCE_SCHEMA} evidence block")
    try:
        return InsightEvidence.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "evidence"
        raise EvidenceError("INSIGHT_EVIDENCE_INVALID", f"{where}: {first['msg']}") from None


def compare_metric_id(row: Mapping[str, Any]) -> str | None:
    """The Data field a Compare metric row reads (`sourceRef.table`.`sourceRef.columns[0]`), None when not declared."""
    ref = row.get("sourceRef") or {}
    columns = ref.get("columns") or []
    return f"{ref['table']}.{columns[0]}" if ref.get("table") and columns else None


@dataclass(frozen=True)
class ComparisonFact:
    """One Compare metric row, as every consumer must show it (read, never recomputed)."""

    comparison_id: str  # "<comparison artifact>@<version>"
    metric_id: str  # the Data field it measures (`sourceRef`)
    metric: str  # Compare's own metric name
    unit: str | None
    subject_value: str
    peer_value: str
    peer_stat: str | None  # e.g. "median"
    delta: str | None
    delta_pct: str | None
    peer_count: int | None
    peer_definition: str | None  # "<peer_definition artifact>@<version>": the explicit peer set
    snapshot_id: str | None
    semantic_config_version: str | None
    refs: dict[str, str]  # field → "<comparison>@<v>#<pointer>" (subject_value, peer_value, delta_pct, peer_count)


def comparison_facts(comparison: Mapping[str, Any]) -> dict[str, ComparisonFact]:
    """metric id → fact, for every Compare row with a declared Data field and both a subject and a peer value."""
    label = f"{comparison['artifact_id']}@{comparison['version']}"
    pd = next((r for r in comparison.get("input_artifact_refs") or [] if r.get("artifact_type") == "peer_definition"), None)
    snapshots = comparison.get("snapshot_refs") or []
    out: dict[str, ComparisonFact] = {}
    for i, row in enumerate((comparison.get("payload") or {}).get("metrics") or []):
        metric_id, bench = compare_metric_id(row), row.get("benchmark") or {}
        if metric_id is None or decimal_of(row.get("subjectValue")) is None or decimal_of(bench.get("value")) is None:
            continue
        base = f"{label}#/metrics/{i}"
        refs = {"subject_value": f"{base}/subjectValue", "peer_value": f"{base}/benchmark/value"}
        if row.get("pctGap") is not None:
            refs["delta_pct"] = f"{base}/pctGap"
        if bench.get("n") is not None:
            refs["peer_count"] = f"{base}/benchmark/n"
        out[metric_id] = ComparisonFact(
            comparison_id=label, metric_id=metric_id, metric=str(row.get("metric")), unit=row.get("unit"),
            subject_value=str(row["subjectValue"]), peer_value=str(bench["value"]), peer_stat=bench.get("stat"),
            delta=None if row.get("absGap") is None else str(row["absGap"]),
            delta_pct=None if row.get("pctGap") is None else str(row["pctGap"]),
            peer_count=bench.get("n"), peer_definition=f"{pd['artifact_id']}@{pd['version']}" if pd else None,
            snapshot_id=snapshots[0] if snapshots else None, semantic_config_version=comparison.get("semantic_config_version"),
            refs=refs,
        )
    return out


def peer_claims(insight_payload: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(insight id, slot, value) of every narrated number that is a mart peer figure — a peer fact Insight does not
    own (only a stale or malformed artifact has one; @2 narration never binds them)."""
    out: list[tuple[str, str, str]] = []
    for item in (insight_payload.get("insight") or {}).get("insights") or []:
        for b in (item.get("claim") or {}).get("numeric_bindings") or []:
            if str(b.get("metric_ref", "")).rsplit("/", 1)[-1] in PEER_RELATIVE_FIELDS:
                out.append((str(item.get("insight_id")), str(b.get("slot")), str(b.get("value"))))
    return out


@dataclass(frozen=True)
class PeerBinding:
    insight_id: str
    finding_id: str
    metric_id: str
    fact: ComparisonFact | None  # Compare's row for the metric; None when the run has no comparison of it


def peer_bindings(insight: Mapping[str, Any], comparison: Mapping[str, Any] | None) -> dict[str, list[PeerBinding]]:
    """narrated insight id → the peer views its finding requires, each bound to Compare's fact (never recomputed)."""
    try:
        evidence = parse_evidence(insight.get("payload") or {})
    except EvidenceError:
        return {}
    facts = comparison_facts(comparison) if comparison is not None else {}
    out: dict[str, list[PeerBinding]] = {}
    for f in evidence.findings:
        for intent in f.visual_intents if f.insight_id else []:
            if intent.question == "target_vs_peer":
                out.setdefault(f.insight_id or "", []).extend(
                    PeerBinding(f.insight_id or "", f.finding_id, m, facts.get(m)) for m in intent.metric_ids)
    return out
