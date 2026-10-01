"""Chart's StepSpec@1 path (WS4): real Insight / Comparison artifacts in, `chart_spec` artifacts out.

1. `draw_chart` with an optional `chart_type` override (must be allowed by the chart policy).
2. `resolve_analysis_inputs`: insight and/or comparison (+ peer_definition) from the Artifact Store, pinned by hash,
   same snapshot / semantic version, all derived from the same Data dataset (vdagent_contracts.step_inputs); the dataset
   itself is read once (pinned by hash) as the canonical source every displayed Data value is checked against.
3. Project — never compute, never read prose — the upstream values into the chart pipeline's own artifact shape:
   - Insight: only its typed `insight_evidence@2` block (vdagent_contracts.insight_evidence). Each `current_value` intent
     metric becomes one KPI per (subject, metric), after its `source_ref` resolves in the dataset to its `value_exact`;
     a `target_vs_peer` intent is fulfilled by Compare's chart of that metric (never drawn from Insight). The claim
     text, `display` strings and `numeric_bindings` are never read: an LLM chose them. A missing or broken block is
     an explicit limitation, never a fallback to the narrative.
   - Comparison: per metric with a subject value and a peer benchmark, a `target_vs_peer` view (the subject value is
     checked against the dataset first); per `scatter` hint a `relationship` view over the ACTUAL peers' values (each
     checked against the dataset).
   - Peer facts are Compare's only: `insight_evidence@2` carries no mart peer figure (a stale block that does is
     rejected as INSIGHT_EVIDENCE_INVALID), and an Insight finding that needs a peer view is linked to Compare's chart.
   Each displayed value keeps `value_exact`, a `source_ref` (`<artifact_id>@<version>#<json pointer>`) and its
   `metric_id`; Insight-derived values also name their `finding_ids` and `evidence_refs`.
4. Run the deterministic pipeline once per view (`ChartAgentService`: validation, evidence map, selection policy,
   dataset, semantic spec, output validation, Vega-Lite + Plotly renderers) over an in-memory store holding only that
   view. No LLM on this path: the visual question and chart type come from the typed upstream intent and the titles
   from the metric catalog, so identical inputs give identical chart specs (Chart AGENT.md §6.13, §6.17).
5. Persist one `chart_spec@1` per chart through `artifact_put`, pinned to the dataset and the upstream artifacts it
   shows, with upstream limitations carried, log one `CHART_SPEC_STORED` line per chart (lineage, no payload), and
   answer with an `AgentReport@1`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactRef as StoreRef
from vdagent_contracts.envelope import ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.insight_evidence import (
    EvidenceError,
    InsightEvidence,
    compare_metric_id,
    parse_evidence,
    same_value,
)
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport, ReportError
from vdagent_contracts.step_inputs import INPUT_ERROR_CLASSES, AnalysisInputs, InputError, Tools, resolve_analysis_inputs
from vdagent_contracts.vega_lite import validate_vega_lite

from .contracts import ArtifactRef, ChartTaskInput, Intent, Scope, VisualTarget
from .errors import ChartError
from .fixture_store import FixtureArtifactStore
from .policy import load_policy
from .service import ChartAgentService

log = logging.getLogger("vdagent.plugin.vdagent_chart")

AGENT, AGENT_VERSION = "chart", "0.2.0"
OPERATIONS = ("draw_chart",)
POLICY_REF = "chart-policy/demo-1.0"  # the only chart ruleset in the repository (chart types and limits)
PEER_QUESTION_TYPES = ("bar", "bullet")
GENERIC_TITLES = {"Target vs peer", "Relationship", "Current value"}

FIELD_DISPLAY = {
    "label": "Căn hộ / benchmark",
    "dom": "Thời gian trên thị trường (ngày)",
    "net_asking_price_per_m2": "Giá ròng/m² (VND)",
}

METRIC_DISPLAY = {
    "dom": "DOM",
    "net_asking_price_per_m2": "Giá ròng/m²",
}

CHART_ERROR_CLASSES: dict[str, ErrorClass] = {
    **INPUT_ERROR_CLASSES,
    "UNKNOWN_OPERATION": ErrorClass.SPEC_ISSUE,
    "INVALID_SPEC": ErrorClass.SPEC_ISSUE,
    "UNSUPPORTED_CHART_TYPE": ErrorClass.SPEC_ISSUE,
    "NOTHING_TO_CHART": ErrorClass.DATA_QUALITY,
    "CHART_FAILED": ErrorClass.DATA_QUALITY,
    "TOOL_FAILED": ErrorClass.TRANSIENT,
}


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chart_type: str | None = None


class _Fail(Exception):
    def __init__(self, state: Literal["rejected", "failed"], code: str, message: str) -> None:
        super().__init__(message)
        self.state, self.code, self.message = state, code, message


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 JSON pointer lookup (`/metrics/0/subjectValue`)."""
    value = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _number(value: Any) -> int | float | None:
    """The plotting value of an exact upstream number (int stays int); None when it is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        exact = Decimal(str(value))
    except InvalidOperation:
        return None
    if not exact.is_finite():
        return None
    return int(exact) if exact == exact.to_integral_value() else float(exact)


@dataclass
class _View:
    view_id: str
    artifact_type: str
    grain: str
    payload: dict[str, Any]
    target: VisualTarget
    bindings: list[dict[str, Any]]  # record_index, field, value_exact, unit, source_ref, metric_id (+ finding_ids, evidence_refs)
    upstream: list[ArtifactType]
    title: str
    lineage: dict[str, Any]  # insight / comparison it came from, metric_ids, finding_ids
    extra_ids: list[str] = field(default_factory=list)


def _ref_label(env: dict[str, Any]) -> str:
    return f"{env['artifact_id']}@{env['version']}"


class _Dataset:
    """The run's Data dataset (pinned by hash): the canonical source every displayed Data value is checked against."""

    def __init__(self, env: dict[str, Any]) -> None:
        self.label, self.payload = _ref_label(env), env["payload"]
        units = self.payload.get("tables", {}).get("dim_unit_master") or []
        self._key_by_code = {u.get("unit_code"): u.get("unit_key") for u in units}

    def value(self, pointer: str) -> Any:
        return resolve_pointer(self.payload, pointer)

    def unit_value(self, metric_id: str, unit_key: Any) -> tuple[bool, Any]:
        """(found, value) of `<table>.<field>` on the row of `unit_key`."""
        table, _, column = metric_id.partition(".")
        for row in self.payload.get("tables", {}).get(table) or []:
            if row.get("unit_key") == unit_key and column in row:
                return True, row[column]
        return False, None

    def unit_key(self, entity: dict[str, Any]) -> Any:
        return entity.get("entityId") or self._key_by_code.get(entity.get("entityCode"))


def _comparison_views(comparison: dict[str, Any], peer_def: dict[str, Any] | None, chart_type: str | None,
                      limitations: list[str], dataset: _Dataset, peer_findings: dict[str, list[str]],
                      insight_label: str | None) -> list[_View]:
    payload, cid = comparison["payload"], _ref_label(comparison)
    subject = payload.get("subject") or {}
    code = subject.get("entityCode") or subject.get("entityId") or "subject"
    values = payload.get("peerValues") or []
    subject_key = dataset.unit_key(next((v for v in values if v.get("role") == "subject"), subject))
    hints = payload.get("chartHints") or []
    ids = {row["metric"]: compare_metric_id(row) for row in payload.get("metrics") or []}
    views: list[_View] = []
    for i, row in enumerate(payload.get("metrics") or []):
        metric, unit, metric_id = row["metric"], row.get("unit"), ids[row["metric"]]
        subject_value, benchmark = row.get("subjectValue"), (row.get("benchmark") or {}).get("value")
        if _number(subject_value) is None or _number(benchmark) is None:
            limitations.append(f"NOT_CHARTED_NULL:{metric}")
            continue
        found, canonical = dataset.unit_value(metric_id, subject_key) if metric_id else (False, None)
        if not found or not same_value(canonical, subject_value):  # the subject's own value is a Data value: check it
            limitations.append(f"VALUE_MISMATCH_WITH_DATASET:comparison:{metric_id or metric}")
            continue
        n = (row.get("benchmark") or {}).get("n")
        hint = next((h.get("chartType") for h in hints if h.get("y") == metric and h.get("chartType") in PEER_QUESTION_TYPES), None)
        base = f"{comparison['artifact_id']}~{metric}"
        records = [{"label": code, metric: _number(subject_value)},
                   {"label": f"Trung vị {n} căn tương đồng", metric: _number(benchmark)}]
        views.append(_View(
            view_id=f"{base}~comparison", artifact_type="comparison", grain="group",
            payload={"comparison_metric": metric, "unit": unit, "grain": "group", "display_records": records,
                     "target_value": _number(subject_value), "peer_aggregate": _number(benchmark),
                     "peer_definition": {"peer_count": n, "peer_definition_ref": _ref_label(peer_def) if peer_def else None}},
            target=VisualTarget(f"vt_{metric}", "target_vs_peer", "report_compilation", chart_type or hint,
                                (f"{base}~metric", f"{base}~comparison")),
            bindings=[
                {"record_index": 0, "field": metric, "value_exact": str(subject_value), "unit": unit, "metric_id": metric_id,
                 "source_ref": f"{cid}#/metrics/{i}/subjectValue"},
                {"record_index": 1, "field": metric, "value_exact": str(benchmark), "unit": unit, "metric_id": metric_id,
                 "source_ref": f"{cid}#/metrics/{i}/benchmark/value"},
            ],
            upstream=[ArtifactType.COMPARISON] + ([ArtifactType.PEER_DEFINITION] if peer_def else []),
            title=f"{metric}: {code} so với trung vị {n} căn tương đồng",
            lineage={"insight": insight_label if peer_findings.get(metric_id or "") else None, "comparison": cid,
                     "metric_ids": [metric_id], "finding_ids": peer_findings.get(metric_id or "", [])},
            extra_ids=[f"{base}~metric"],
        ))
    for hint in hints:
        if hint.get("chartType") != "scatter":
            continue
        x, y = hint.get("x"), hint.get("y")
        x_id, y_id = ids.get(str(x)), ids.get(str(y))
        records, bindings, unbacked = [], [], False
        for j, entry in enumerate(values):
            vx, vy = (entry.get("values") or {}).get(x), (entry.get("values") or {}).get(y)
            if _number(vx) is None or _number(vy) is None:
                limitations.append(f"NOT_CHARTED_NULL:{entry.get('entityCode')}")
                continue
            key = dataset.unit_key(entry)
            checks = [dataset.unit_value(m, key) if m else (False, None) for m in (x_id, y_id)]
            if not all(found and same_value(value, shown) for (found, value), shown in zip(checks, (vx, vy), strict=True)):
                unbacked = True
                break
            k = len(records)
            records.append({"label": entry.get("entityCode"), x: _number(vx), y: _number(vy)})
            bindings += [{"record_index": k, "field": x, "value_exact": str(vx), "unit": None, "metric_id": x_id,
                          "source_ref": f"{cid}#/peerValues/{j}/values/{x}"},
                         {"record_index": k, "field": y, "value_exact": str(vy), "unit": None, "metric_id": y_id,
                          "source_ref": f"{cid}#/peerValues/{j}/values/{y}"}]
        if unbacked:  # one peer value the dataset does not hold: the whole relationship view is withheld
            limitations.append(f"VALUE_MISMATCH_WITH_DATASET:comparison:peerValues:{x}~{y}")
            continue
        if len(records) < 2:
            continue
        vid = f"{comparison['artifact_id']}~scatter~{x}~{y}"
        views.append(_View(
            view_id=vid, artifact_type="metric", grain="unit",
            payload={"unit": None, "grain": "unit", "records": records},
            target=VisualTarget(f"vt_{x}_vs_{y}", "relationship", "report_compilation", "scatter", (vid,)),
            bindings=bindings, upstream=[ArtifactType.COMPARISON] + ([ArtifactType.PEER_DEFINITION] if peer_def else []),
            title=str(hint.get("purpose") or f"{x} và {y}"),
            lineage={"insight": None, "comparison": cid, "metric_ids": [x_id, y_id], "finding_ids": []},
        ))
    return views


def _field_display(field: str) -> str:
    return FIELD_DISPLAY.get(field, field.replace("_", " "))


def _metric_display(metric: str) -> str:
    return METRIC_DISPLAY.get(metric, metric.replace("_", " "))


def _view_presentation(view: _View) -> dict[str, Any]:
    target = view.target.visual_question
    if target == "target_vs_peer":
        metric = str(view.payload.get("comparison_metric") or "")
        n = (view.payload.get("peer_definition") or {}).get("peer_count")
        code = (view.payload.get("display_records") or [{}])[0].get("label") or "Căn mục tiêu"
        title = f"{_metric_display(metric)} của {code} so với trung vị {n} căn tương đồng" if n else f"{_metric_display(metric)} của {code} so với benchmark"
        return {
            "title": title,
            "subtitle": "So sánh giá trị của căn mục tiêu với benchmark peer đã được Compare xác định.",
            "axes": {
                "x": {"title": {"format": "plain", "value": "Căn hộ / benchmark"}},
                "y": {"title": {"format": "plain", "value": _field_display(metric)}},
            },
            "legend": {"title": "Chỉ số", "items": {metric: _metric_display(metric)}},
        }
    if target == "relationship":
        records = view.payload.get("records") or []
        fields = [k for k in (records[0] if records else {}) if k != "label"]
        x = fields[0] if fields else "x"
        y = fields[1] if len(fields) > 1 else "y"
        return {
            "title": f"{_metric_display(x)} và {_metric_display(y)} trong nhóm tương đồng",
            "subtitle": "Mỗi điểm là một căn trong nhóm peer thực tế của Compare.",
            "axes": {
                "x": {"title": {"format": "plain", "value": _field_display(x)}},
                "y": {"title": {"format": "plain", "value": _field_display(y)}},
            },
        }
    return {"title": view.title, "subtitle": "Giá trị từ bằng chứng của Insight, đã đối chiếu với dataset Data của lần chạy."}


def _needs_business_title(title: str) -> bool:
    return title in GENERIC_TITLES or "_" in title or not title.strip()


def _axis_title(axes: dict[str, Any], axis_name: str) -> str | None:
    axis = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else None
    title_spec = axis.get("title") if isinstance(axis, dict) and isinstance(axis.get("title"), dict) else None
    value = title_spec.get("value") if isinstance(title_spec, dict) else None
    return str(value) if value else None


def _apply_business_presentation(local: dict[str, Any], view: _View) -> tuple[str, dict[str, Any]]:
    default = _view_presentation(view)
    presentation = local.get("presentation") if isinstance(local.get("presentation"), dict) else {}
    title = str(presentation.get("title") or "")
    if _needs_business_title(title):
        title = str(default["title"])
    axes = default.get("axes") if isinstance(default.get("axes"), dict) else {}
    render_spec = local.get("render_spec") if isinstance(local.get("render_spec"), dict) else {}
    layout = render_spec.get("layout") if isinstance(render_spec.get("layout"), dict) else {}
    if isinstance(layout.get("title"), dict):
        layout["title"]["text"] = title
    for axis_name, layout_key in (("x", "xaxis"), ("y", "yaxis")):
        axis_title = _axis_title(axes, axis_name)
        axis_layout = layout.get(layout_key) if isinstance(layout.get(layout_key), dict) else None
        if axis_title and axis_layout and isinstance(axis_layout.get("title"), dict):
            axis_layout["title"]["text"] = axis_title
    semantic = local.get("semantic_spec") if isinstance(local.get("semantic_spec"), dict) else {}
    semantic_presentation = semantic.get("presentation") if isinstance(semantic.get("presentation"), dict) else {}
    semantic_presentation["title"] = title
    semantic_presentation["title_spec"] = {"format": "plain", "value": title}
    for axis_name, semantic_key in (("x", "x_axis"), ("y", "y_axis")):
        axis = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else None
        if axis:
            semantic_presentation[semantic_key] = axis
    semantic["presentation"] = semantic_presentation
    return title, axes


def _apply_vega_axis_titles(vega: dict[str, Any], axes: dict[str, Any]) -> dict[str, Any]:
    encoding = vega.get("encoding")
    if not isinstance(encoding, dict):
        return vega
    for channel, axis_name in (("x", "x"), ("y", "y")):
        axis_title = _axis_title(axes, axis_name)
        if not axis_title or not isinstance(encoding.get(channel), dict):
            continue
        axis = encoding[channel].get("axis")
        if not isinstance(axis, dict):
            axis = {}
        encoding[channel]["axis"] = {**axis, "title": axis_title}
    return vega


@dataclass
class _Kpi:
    metric_id: str
    label: str
    value_exact: str
    unit: str
    source_ref: str
    subject: str
    finding_ids: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    conflict: bool = False


def _insight_evidence(insight: dict[str, Any], step: StepSpec, inputs: AnalysisInputs,
                      limitations: list[str]) -> InsightEvidence | None:
    try:
        evidence = parse_evidence(insight["payload"])
    except EvidenceError as exc:
        limitations.append(f"{exc.code}:{exc.message}")
        return None
    pinned = (evidence.dataset_ref.artifact_id, evidence.dataset_ref.version, evidence.dataset_ref.content_hash)
    expected = (inputs.dataset_ref.artifact_id, inputs.dataset_ref.version, inputs.dataset_ref.content_hash)
    if pinned != expected or (evidence.snapshot_id, evidence.semantic_config_version) != (step.snapshot_id, step.semantic_config_version):
        limitations.append("INSIGHT_EVIDENCE_INVALID:the evidence is not pinned to this run's dataset / snapshot / semantic version")
        return None
    return evidence


def _peer_findings(evidence: InsightEvidence | None) -> dict[str, list[str]]:
    """metric id → findings whose `target_vs_peer` intent asks for Compare's view of it."""
    out: dict[str, list[str]] = {}
    for f in evidence.findings if evidence else []:
        for intent in f.visual_intents:
            if intent.question == "target_vs_peer":
                for metric_id in intent.metric_ids:
                    out.setdefault(metric_id, []).append(f.finding_id)
    return out


def _insight_views(insight: dict[str, Any], evidence: InsightEvidence, chart_type: str | None, dataset: _Dataset,
                   compared: set[str], limitations: list[str], skipped: list[str]) -> list[_View]:
    """One KPI per (subject, metric) of the `current_value` intents, each value checked against the dataset."""
    iid = _ref_label(insight)
    kpis: dict[tuple[str, str], _Kpi] = {}
    for fi, f in enumerate(evidence.findings):
        if not f.visual_intents:
            skipped.append(f"NO_VISUAL_INTENT:{f.finding_id}")
        by_id = {m.metric_id: (mi, m) for mi, m in enumerate(f.metrics)}
        for intent in f.visual_intents:
            if intent.question == "target_vs_peer":
                limitations += [f"VISUAL_NEEDS_COMPARISON:{f.finding_id}:{m}" for m in intent.metric_ids if m not in compared]
                continue
            for metric_id in intent.metric_ids:
                mi, m = by_id[metric_id]
                where = f"{f.finding_id}/{metric_id}"
                if not m.source_ref or not m.source_ref.startswith(f"{dataset.label}#"):
                    limitations.append(f"EVIDENCE_UNRESOLVED:{where}")
                    continue
                try:
                    canonical = dataset.value(m.source_ref.split("#", 1)[1])
                except (KeyError, IndexError, ValueError, TypeError):
                    limitations.append(f"EVIDENCE_UNRESOLVED:{where}")
                    continue
                if not same_value(canonical, m.value_exact):
                    limitations.append(f"EVIDENCE_VALUE_MISMATCH:{where}")
                    continue
                kpi = kpis.setdefault((f.subject.id, metric_id), _Kpi(metric_id, m.label, m.value_exact, m.unit,
                                                                      m.source_ref, f.subject.label))
                if not same_value(kpi.value_exact, m.value_exact):  # one subject, one metric, two values: neither shown
                    kpi.conflict = True
                kpi.finding_ids.append(f.finding_id)
                kpi.evidence_refs.append(f"{iid}#/evidence/findings/{fi}/metrics/{mi}/value_exact")
    views: list[_View] = []
    for n, kpi in enumerate(kpis.values()):
        if kpi.conflict:
            limitations.append(f"CONFLICTING_VALUES:insight:{kpi.metric_id}")
            continue
        vid = f"{insight['artifact_id']}~kpi~{n}"
        views.append(_View(
            view_id=vid, artifact_type="metric", grain="unit",
            payload={"unit": kpi.unit, "grain": "unit", "records": [{"label": kpi.label, "value": _number(kpi.value_exact)}]},
            target=VisualTarget(f"vt_kpi_{n}", "current_value", "report_compilation", chart_type or "kpi_card", (vid,)),
            bindings=[{"record_index": 0, "field": "value", "value_exact": kpi.value_exact, "unit": kpi.unit,
                       "metric_id": kpi.metric_id, "source_ref": kpi.source_ref, "finding_ids": kpi.finding_ids,
                       "evidence_refs": kpi.evidence_refs}],
            upstream=[ArtifactType.INSIGHT], title=f"{kpi.label} của căn {kpi.subject}",
            lineage={"insight": iid, "comparison": None, "metric_ids": [kpi.metric_id], "finding_ids": kpi.finding_ids},
        ))
    return views


def _as_chart_artifact(view_id: str, artifact_type: str, grain: str, payload: dict[str, Any], step: StepSpec,
                       projects: list[str]) -> dict[str, Any]:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return {"artifact_id": view_id, "version": 1, "artifact_type": artifact_type, "run_id": step.run_id,
            "status": "validated", "content_hash": "sha256:" + hashlib.sha256(body.encode()).hexdigest(),
            "scope": {"project_ids": projects, "snapshot_id": step.snapshot_id, "data_grain": grain}, "payload": payload}


def _report(step: StepSpec, state: str, *, error: ReportError | None = None, refs: list[StoreRef] | None = None,
            warnings: list[str] | None = None, partial: bool = False, summary: str = "") -> AgentReport:
    return AgentReport.model_validate({
        "run_id": step.run_id, "step_id": step.step_id, "idempotency_key": step.idempotency_key, "state": state,
        "partial": partial, "artifact_refs": [r.model_dump(mode="json") for r in refs or []],
        "snapshot_id": step.snapshot_id, "semantic_config_version": step.semantic_config_version,
        "summary": summary or (error.message if error else ""), "warnings": sorted(set(warnings or [])), "error": error,
    })


async def run_step(step: StepSpec, tools: Tools) -> AgentReport:
    started = time.monotonic()
    try:
        report = await _run(step, tools)
    except InputError as exc:
        report = _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message))
    except _Fail as exc:
        retryable = CHART_ERROR_CLASSES.get(exc.code) is ErrorClass.TRANSIENT
        report = _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message, retryable=retryable))
    _event("CHART_STEP_DONE", run_id=step.run_id, step_id=step.step_id, state=report.state, charts=len(report.artifact_refs),
           error=report.error.code if report.error else None, warnings=len(report.warnings),
           latency_ms=int((time.monotonic() - started) * 1000))
    return report


def _event(name: str, **fields: Any) -> None:
    """One structured log line (lineage and status only, never a payload)."""
    log.info(json.dumps({"event": name, **fields}, ensure_ascii=False, default=str))


async def _dataset(tools: Tools, ref: StoreRef) -> _Dataset:
    try:
        env = await tools.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})
    except Exception as exc:
        raise _Fail("failed", "TOOL_FAILED", f"artifact_get of the dataset failed: {exc}") from None
    if env.get("content_hash") != ref.content_hash:
        raise InputError("INPUT_HASH_MISMATCH", f"{ref.artifact_id}@{ref.version}: content hash does not match the stored version")
    return _Dataset(env)


def _parse_numbers(vega: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Non-integer values are stored as decimal strings (no float in the store): tell Vega-Lite to parse them."""
    fields = sorted({k for r in records for k, v in r.items() if isinstance(v, float)})
    if fields and isinstance(vega.get("data"), dict):
        vega = {**vega, "data": {**vega["data"], "format": {"parse": {f: "number" for f in fields}}}}
    return vega


async def _run(step: StepSpec, tools: Tools) -> AgentReport:
    if step.operation not in OPERATIONS:
        raise _Fail("rejected", "UNKNOWN_OPERATION", f"chart serves {', '.join(OPERATIONS)}, not {step.operation!r}")
    try:
        spec = ChartSpec.model_validate(step.spec)
    except ValidationError as exc:
        raise _Fail("rejected", "INVALID_SPEC", f"invalid draw_chart spec: {exc.error_count()} error(s)") from None
    policy = load_policy(POLICY_REF)
    if spec.chart_type is not None and spec.chart_type not in policy.allowed_chart_types:
        raise _Fail("rejected", "UNSUPPORTED_CHART_TYPE", f"chart type {spec.chart_type!r} is not allowed by {POLICY_REF}")

    inputs: AnalysisInputs = await resolve_analysis_inputs(step, tools)
    dataset = await _dataset(tools, inputs.dataset_ref)
    limitations: list[str] = [*inputs.limitations, *(f"UPSTREAM_MISSING:{m}" for m in inputs.missing)]
    skipped: list[str] = []
    evidence = _insight_evidence(inputs.insight, step, inputs, limitations) if inputs.insight is not None else None
    insight_label = _ref_label(inputs.insight) if inputs.insight is not None else None
    views: list[_View] = []
    if inputs.comparison is not None:
        views += _comparison_views(inputs.comparison, inputs.peer_definition, spec.chart_type, limitations, dataset,
                                   _peer_findings(evidence), insight_label)
    compared = {m for v in views if v.target.visual_question == "target_vs_peer" for m in v.lineage["metric_ids"]}
    if inputs.insight is not None and evidence is not None:
        views += _insight_views(inputs.insight, evidence, spec.chart_type, dataset, compared, limitations, skipped)
    for reason in skipped:
        _event("CHART_FINDING_SKIPPED", run_id=step.run_id, step_id=step.step_id, reason=reason)
    if not views:
        reasons = sorted({c for c in limitations if not c.startswith(("BLOCKED:", "CONFIG_PENDING:", "METRIC_UNAVAILABLE:",
                                                                      "WINDOW_INCOMPLETE:", "DQ_", "FIELD_UNAVAILABLE:",
                                                                      "SYNTHETIC_SOURCE:", "SNAPSHOT_STATUS_ASSUMED"))})
        raise _Fail("failed", "NOTHING_TO_CHART", "the inputs hold no chartable, verified value: "
                    + "; ".join([*reasons, *skipped] or ["no visual intent and no comparison metric"]))

    projects = inputs.authorized_project_ids
    refs: list[StoreRef] = []
    for view in views:
        # One pipeline task per view: the output validator ties a chart's dataset grain to its task scope grain.
        store_views = [_as_chart_artifact(view.view_id, view.artifact_type, view.grain, view.payload, step, projects)]
        for extra in view.extra_ids:  # target_vs_peer also needs the subject's metric view
            store_views.append(_as_chart_artifact(extra, "metric", "unit", {"unit": view.payload["unit"], "grain": "unit",
                                                                           "records": [view.payload["display_records"][0]]},
                                                  step, projects))
        task = ChartTaskInput(
            schema_version="chart-task/2.0", run_id=step.run_id, task_id=f"chart_{step.step_id}", mode="report_compilation",
            scope=Scope(snapshot_id=step.snapshot_id, data_grain=view.grain), visual_targets=(view.target,),
            artifact_refs=tuple(ArtifactRef(a["artifact_id"], 1, a["content_hash"]) for a in store_views),
            policy_ref=POLICY_REF, idempotency_key=step.idempotency_key,
            intent=Intent("report_compilation", step.original_question),
        )
        started = time.monotonic()
        service = ChartAgentService(FixtureArtifactStore(store_views))  # in-memory, holds only this view; no LLM
        try:
            result = service.execute(task)
        except ChartError as exc:
            limitations.append(f"CHART_TARGET_FAILED:{view.target.target_id}:{exc.code}")
            _event("CHART_TARGET_REJECTED", run_id=step.run_id, step_id=step.step_id, target_id=view.target.target_id,
                   code=exc.code, metric_ids=view.lineage["metric_ids"])
            continue
        for error in result.errors:
            limitations.append(f"CHART_TARGET_FAILED:{error['target_id']}:{error['code']}")
        [target] = result.target_results
        if target.status != "success" or target.chart_ref is None:
            continue
        local = service.artifacts[target.chart_ref.removesuffix("@1")]
        chart_title, axes = _apply_business_presentation(local, view)
        vega = {
            **_parse_numbers(local["semantic_spec"]["vega_render_spec"], local["dataset"]["records"]),
            "title": chart_title,
        }
        vega = _apply_vega_axis_titles(vega, axes)
        if problems := validate_vega_lite(vega):  # WS7 F-01: never store a spec the UI cannot render
            limitations.append(f"CHART_TARGET_FAILED:{target.target_id}:INVALID_VEGA_LITE:{problems[0]}")
            _event("CHART_TARGET_REJECTED", run_id=step.run_id, step_id=step.step_id, target_id=target.target_id,
                   code="INVALID_VEGA_LITE", metric_ids=view.lineage["metric_ids"])
            continue
        semantic = {k: v for k, v in local["semantic_spec"].items() if k not in ("render_spec", "vega_render_spec")}
        dataset = local["dataset"]
        payload = {
            "chart_id": local["artifact_id"], "target_id": target.target_id, "visual_question": view.target.visual_question,
            "chart_type": local["chart_type"], "title": chart_title,
            "vega_lite": vega,
            "plotly": local["render_spec"], "semantic_spec": semantic, "dataset": dataset, "bindings": view.bindings,
            "selection": local["selection"], "validation": local["semantic_spec"].get("validation"), "policy_ref": POLICY_REF,
            "lineage": view.lineage,
        }  # fmt: skip
        upstream = [inputs.refs[k] for k in view.upstream if k in inputs.refs]
        chart_limits = sorted(set(limitations))
        draft = {
            "artifact_type": "chart_spec", "schema_version": "chart_spec@1",
            "status": "PARTIAL" if chart_limits else "VALID",
            "producer": {"agent": AGENT, "agent_version": AGENT_VERSION},
            "snapshot_refs": [step.snapshot_id], "semantic_config_version": step.semantic_config_version,
            "source_refs": sorted({b["source_ref"].split("#", 1)[0] for b in view.bindings}),
            "input_artifact_refs": [r.model_dump(mode="json") for r in [inputs.dataset_ref, *upstream]],
            "limitations": chart_limits, "payload": payload,
        }  # fmt: skip
        try:
            stored = await tools.call("artifact_put", {"draft_json": canonical_json(json.loads(json.dumps(draft), parse_float=Decimal))})
        except Exception as exc:
            raise _Fail("failed", "TOOL_FAILED", f"artifact_put failed: {exc}") from None
        refs.append(StoreRef(artifact_id=stored["artifact_id"], version=stored["version"], artifact_type=ArtifactType.CHART_SPEC,
                             content_hash=stored["content_hash"]))
        _event("CHART_SPEC_STORED", run_id=step.run_id, step_id=step.step_id, chart_artifact_id=stored["artifact_id"],
               version=stored["version"], visual_question=view.target.visual_question, chart_type=local["chart_type"],
               metric_ids=view.lineage["metric_ids"], finding_ids=view.lineage["finding_ids"],
               insight_artifact=view.lineage["insight"], comparison_artifact=view.lineage["comparison"],
               source_refs=[b["source_ref"] for b in view.bindings][:12], validation="pass",
               latency_ms=int((time.monotonic() - started) * 1000))
    if not refs:
        raise _Fail("failed", "CHART_FAILED", "no chart passed validation: " + "; ".join(sorted(set(limitations))))
    warnings = sorted(set(limitations))
    return _report(step, "completed", refs=refs, warnings=warnings, partial=bool(warnings),
                   summary=f"{len(refs)} biểu đồ @ {step.snapshot_id} từ {', '.join(k.value for k in inputs.refs)}.")
