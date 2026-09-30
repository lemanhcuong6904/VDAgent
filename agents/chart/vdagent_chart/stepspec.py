"""Chart's StepSpec@1 path (WS4): real Insight / Comparison artifacts in, `chart_spec` artifacts out.

1. `draw_chart` with an optional `chart_type` override (must be allowed by the chart policy).
2. `resolve_analysis_inputs`: insight and/or comparison (+ peer_definition) from the Artifact Store, pinned by hash,
   same snapshot / semantic version, all derived from the same Data dataset (vdagent_contracts.step_inputs).
3. Project — never compute — the upstream values into the chart pipeline's own artifact shape ("views"):
   - per comparison metric with a subject value and a peer benchmark: a `target_vs_peer` view
     (subject value vs the benchmark the engine reported), preferred type from `chartHints`;
   - per `scatter` chart hint: a `relationship` view over `peerValues` (the ACTUAL peers of the comparison);
   - per Insight numeric binding: a `current_value` (KPI) view.
   Each displayed value keeps `value_exact` (the upstream string/int) and a `source_ref`
   (`<artifact_id>@<version>#<json pointer>`). Null upstream values are not charted (limitation, never 0).
4. Run the unchanged deterministic pipeline once per view (`ChartAgentService`: validation, evidence map, selection
   policy, dataset, optional bounded LLM presentation reasoning, semantic spec, output validation, Vega-Lite + Plotly
   renderers) over an in-memory exact-version store holding only those views. No demo artifact, no mock upstream.
5. Persist one `chart_spec@1` per chart through `artifact_put`, pinned to the dataset and the upstream artifacts it
   shows, with upstream limitations carried; answer with an `AgentReport@1`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactRef as StoreRef
from vdagent_contracts.envelope import ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport, ReportError
from vdagent_contracts.step_inputs import INPUT_ERROR_CLASSES, AnalysisInputs, InputError, Tools, resolve_analysis_inputs
from vdagent_contracts.vega_lite import validate_vega_lite

from .contracts import ArtifactRef, ChartTaskInput, Intent, Scope, VisualTarget
from .errors import ChartError
from .fixture_store import FixtureArtifactStore
from .llm import VisualReasoner
from .policy import load_policy
from .service import ChartAgentService

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
    bindings: list[dict[str, Any]]  # record_index, field, value_exact, unit, source_ref
    upstream: list[ArtifactType]
    title: str
    extra_ids: list[str] = field(default_factory=list)


def _ref_label(env: dict[str, Any]) -> str:
    return f"{env['artifact_id']}@{env['version']}"


def _comparison_views(comparison: dict[str, Any], peer_def: dict[str, Any] | None, chart_type: str | None,
                      limitations: list[str]) -> list[_View]:
    payload, cid = comparison["payload"], _ref_label(comparison)
    subject = payload.get("subject") or {}
    code = subject.get("entityCode") or subject.get("entityId") or "subject"
    hints = payload.get("chartHints") or []
    peers = len((peer_def or {}).get("payload", {}).get("peers") or [])
    views: list[_View] = []
    for i, row in enumerate(payload.get("metrics") or []):
        metric, unit = row["metric"], row.get("unit")
        subject_value, benchmark = row.get("subjectValue"), (row.get("benchmark") or {}).get("value")
        if _number(subject_value) is None or _number(benchmark) is None:
            limitations.append(f"NOT_CHARTED_NULL:{metric}")
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
                {"record_index": 0, "field": metric, "value_exact": str(subject_value), "unit": unit,
                 "source_ref": f"{cid}#/metrics/{i}/subjectValue"},
                {"record_index": 1, "field": metric, "value_exact": str(benchmark), "unit": unit,
                 "source_ref": f"{cid}#/metrics/{i}/benchmark/value"},
            ],
            upstream=[ArtifactType.COMPARISON] + ([ArtifactType.PEER_DEFINITION] if peer_def else []),
            title=f"{metric}: {code} so với trung vị {n} căn tương đồng",
            extra_ids=[f"{base}~metric"],
        ))
    values = payload.get("peerValues") or []
    for hint in hints:
        if hint.get("chartType") != "scatter":
            continue
        x, y = hint.get("x"), hint.get("y")
        records, bindings = [], []
        for j, entry in enumerate(values):
            vx, vy = (entry.get("values") or {}).get(x), (entry.get("values") or {}).get(y)
            if _number(vx) is None or _number(vy) is None:
                limitations.append(f"NOT_CHARTED_NULL:{entry.get('entityCode')}")
                continue
            k = len(records)
            records.append({"label": entry.get("entityCode"), x: _number(vx), y: _number(vy)})
            bindings += [{"record_index": k, "field": x, "value_exact": str(vx), "unit": None,
                          "source_ref": f"{cid}#/peerValues/{j}/values/{x}"},
                         {"record_index": k, "field": y, "value_exact": str(vy), "unit": None,
                          "source_ref": f"{cid}#/peerValues/{j}/values/{y}"}]
        if len(records) < 2:
            continue
        vid = f"{comparison['artifact_id']}~scatter~{x}~{y}"
        views.append(_View(
            view_id=vid, artifact_type="metric", grain="unit",
            payload={"unit": None, "grain": "unit", "records": records},
            target=VisualTarget(f"vt_{x}_vs_{y}", "relationship", "report_compilation", "scatter", (vid,)),
            bindings=bindings, upstream=[ArtifactType.COMPARISON] + ([ArtifactType.PEER_DEFINITION] if peer_def else []),
            title=str(hint.get("purpose") or f"{x} và {y}"),
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
    return {"title": view.title, "subtitle": "Giá trị được trích từ Insight artifact."}


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


def _insight_views(insight: dict[str, Any], chart_type: str | None, limitations: list[str]) -> list[_View]:
    iid = _ref_label(insight)
    views: list[_View] = []
    seen: set[tuple[str, str, str]] = set()
    for ii, item in enumerate(insight["payload"]["insight"]["insights"]):
        label = (item.get("subject") or {}).get("label") or item.get("insight_id")
        for bi, b in enumerate(item["claim"]["numeric_bindings"]):
            if _number(b.get("value")) is None:
                limitations.append(f"INVALID_BINDING:{item.get('insight_id')}/{b.get('slot')}")
                continue
            key = (str(label), str(b.get("slot")), str(b.get("value")))
            if key in seen:
                continue  # the same number bound again by another insight: one KPI is enough
            seen.add(key)
            vid = f"{insight['artifact_id']}~kpi~{ii}~{bi}"
            views.append(_View(
                view_id=vid, artifact_type="metric", grain="unit",
                payload={"unit": b.get("unit"), "grain": "unit", "records": [{"label": f"{label} · {b.get('slot')}", "value": _number(b["value"])}]},
                target=VisualTarget(f"vt_kpi_{ii}_{bi}", "current_value", "report_compilation", chart_type, (vid,)),
                bindings=[{"record_index": 0, "field": "value", "value_exact": str(b["value"]), "unit": b.get("unit"),
                           "source_ref": f"{iid}#/insight/insights/{ii}/claim/numeric_bindings/{bi}/value"}],
                upstream=[ArtifactType.INSIGHT], title=f"{label}: {b.get('display') or b.get('slot')}",
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


async def run_step(step: StepSpec, tools: Tools, *, reasoner: VisualReasoner | None = None) -> AgentReport:
    try:
        return await _run(step, tools, reasoner=reasoner)
    except InputError as exc:
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message))
    except _Fail as exc:
        retryable = CHART_ERROR_CLASSES.get(exc.code) is ErrorClass.TRANSIENT
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message, retryable=retryable))


def _parse_numbers(vega: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Non-integer values are stored as decimal strings (no float in the store): tell Vega-Lite to parse them."""
    fields = sorted({k for r in records for k, v in r.items() if isinstance(v, float)})
    if fields and isinstance(vega.get("data"), dict):
        vega = {**vega, "data": {**vega["data"], "format": {"parse": {f: "number" for f in fields}}}}
    return vega


async def _run(step: StepSpec, tools: Tools, *, reasoner: VisualReasoner | None = None) -> AgentReport:
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
    limitations: list[str] = [*inputs.limitations, *(f"UPSTREAM_MISSING:{m}" for m in inputs.missing)]
    views: list[_View] = []
    if inputs.comparison is not None:
        views += _comparison_views(inputs.comparison, inputs.peer_definition, spec.chart_type, limitations)
    if inputs.insight is not None:
        views += _insight_views(inputs.insight, spec.chart_type, limitations)
    if not views:
        raise _Fail("failed", "NOTHING_TO_CHART", "the inputs hold no chartable, non-null value")

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
        service = ChartAgentService(
            FixtureArtifactStore(store_views),
            reasoner=reasoner,
        )  # in-memory, holds only this projected view
        try:
            result = await service.execute_async(task) if reasoner is not None else service.execute(task)
        except ChartError as exc:
            limitations.append(f"CHART_TARGET_FAILED:{view.target.target_id}:{exc.code}")
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
            continue
        semantic = {k: v for k, v in local["semantic_spec"].items() if k not in ("render_spec", "vega_render_spec")}
        dataset = local["dataset"]
        payload = {
            "chart_id": local["artifact_id"], "target_id": target.target_id, "visual_question": view.target.visual_question,
            "chart_type": local["chart_type"], "title": chart_title,
            "vega_lite": vega,
            "plotly": local["render_spec"], "semantic_spec": semantic, "dataset": dataset, "bindings": view.bindings,
            "selection": local["selection"], "validation": local["semantic_spec"].get("validation"), "policy_ref": POLICY_REF,
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
    if not refs:
        raise _Fail("failed", "CHART_FAILED", "no chart passed validation: " + "; ".join(sorted(set(limitations))))
    warnings = sorted(set(limitations))
    return _report(step, "completed", refs=refs, warnings=warnings, partial=bool(warnings),
                   summary=f"{len(refs)} biểu đồ @ {step.snapshot_id} từ {', '.join(k.value for k in inputs.refs)}.")
