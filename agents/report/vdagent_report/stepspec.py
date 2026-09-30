"""Report's StepSpec@1 path (WS6, offline Report Mode): real artifacts in, one evidence-checked report out.

1. `draft_report` with an optional `title`.
2. `resolve_analysis_inputs(..., chart_specs=True)`: insight and/or comparison (+ peer_definition) and any
   chart_spec, pinned by hash, readable for this user, same snapshot / semantic version, all from one dataset.
3. `compose_report`: the six sections, every number a Statement with its exact upstream value and source_ref.
4. Evidence validation: every statement and every chart binding is re-resolved against the stored artifacts;
   charts must carry the chart_spec fields and a Vega-Lite `$schema`. Any failure → `EVIDENCE_INVALID`, nothing is
   saved (a report with broken lineage is never stored, let alone VALID).
5. Delivery through the existing `save_report` (markdown with `{{chart_spec:<id>@<v>}}` embeds, validated by the
   Backend) → `rp_…`; then the structured `report@1` artifact through `artifact_put`, pinned to the dataset and every
   input. Limitations are carried, so the artifact is PARTIAL whenever anything is missing.
No LLM, no Jev judge; the LangGraph path stays for free text when an LLM is configured.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport, ReportError
from vdagent_contracts.step_inputs import INPUT_ERROR_CLASSES, InputError, Tools, resolve_analysis_inputs

from .compose import compose_report, validate_chart, validate_statements

AGENT, AGENT_VERSION = "report", "0.2.0"
OPERATIONS = ("draft_report",)

REPORT_ERROR_CLASSES: dict[str, ErrorClass] = {
    **INPUT_ERROR_CLASSES,
    "UNKNOWN_OPERATION": ErrorClass.SPEC_ISSUE,
    "INVALID_SPEC": ErrorClass.SPEC_ISSUE,
    "EVIDENCE_INVALID": ErrorClass.WRONG_RESULT,
    "REPORT_SAVE_FAILED": ErrorClass.TRANSIENT,
    "TOOL_FAILED": ErrorClass.TRANSIENT,
}


class ReportSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = None


class _Fail(Exception):
    def __init__(self, state: Literal["rejected", "failed"], code: str, message: str) -> None:
        super().__init__(message)
        self.state, self.code, self.message = state, code, message


def _report(step: StepSpec, state: str, *, error: ReportError | None = None, refs: list[ArtifactRef] | None = None,
            warnings: list[str] | None = None, partial: bool = False, summary: str = "") -> AgentReport:
    return AgentReport.model_validate({
        "run_id": step.run_id, "step_id": step.step_id, "idempotency_key": step.idempotency_key, "state": state,
        "partial": partial, "artifact_refs": [r.model_dump(mode="json") for r in refs or []],
        "snapshot_id": step.snapshot_id, "semantic_config_version": step.semantic_config_version,
        "summary": summary or (error.message if error else ""), "warnings": sorted(set(warnings or [])), "error": error,
    })


async def run_step(step: StepSpec, tools: Tools) -> AgentReport:
    try:
        return await _run(step, tools)
    except InputError as exc:
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message))
    except _Fail as exc:
        retryable = REPORT_ERROR_CLASSES.get(exc.code) is ErrorClass.TRANSIENT
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message, retryable=retryable))


def _pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


async def _run(step: StepSpec, tools: Tools) -> AgentReport:
    if step.operation not in OPERATIONS:
        raise _Fail("rejected", "UNKNOWN_OPERATION", f"report serves {', '.join(OPERATIONS)}, not {step.operation!r}")
    try:
        spec = ReportSpec.model_validate(step.spec)
    except ValidationError as exc:
        raise _Fail("rejected", "INVALID_SPEC", f"invalid draft_report spec: {exc.error_count()} error(s)") from None
    inputs = await resolve_analysis_inputs(step, tools, chart_specs=True)
    doc = compose_report(inputs, step.original_question, step.snapshot_id or "", step.semantic_config_version or "", spec.title)

    # evidence validation against the stored artifacts (fetched once each, user-scoped)
    cache: dict[str, dict[str, Any]] = {}
    for env in (inputs.insight, inputs.comparison, inputs.peer_definition, *inputs.charts):
        if env is not None:
            cache[f"{env['artifact_id']}@{env['version']}"] = env["payload"]
    wanted = {st.source_ref.split("#", 1)[0] for st in doc.statements if st.source_ref}
    wanted |= {b["source_ref"].split("#", 1)[0] for c in inputs.charts for b in (c["payload"].get("bindings") or []) if b.get("source_ref")}
    for ref in sorted(wanted - set(cache)):
        artifact_id, _, version = ref.partition("@")
        try:
            cache[ref] = (await tools.call("artifact_get", {"artifact_id": artifact_id, "version": int(version)}))["payload"]
        except Exception:
            continue  # unresolvable: reported by the validators below

    def lookup(source_ref: str) -> Any:
        ref, pointer = source_ref.split("#", 1)
        return _pointer(cache[ref], pointer)

    errors = validate_statements(doc.statements, lookup)
    bindings_checked = 0
    for chart in inputs.charts:
        n, chart_errors = validate_chart(chart, lookup)
        bindings_checked += n
        errors += chart_errors
    if errors:
        raise _Fail("failed", "EVIDENCE_INVALID", "; ".join(errors[:5]))
    validation = {"result": "pass", "statements_checked": len(doc.statements), "chart_bindings_checked": bindings_checked,
                  "charts_checked": len(inputs.charts)}

    try:
        saved = await tools.call("save_report", {"title": doc.title, "markdown": doc.markdown})
    except Exception as exc:
        raise _Fail("failed", "REPORT_SAVE_FAILED", f"save_report failed: {exc}") from None
    upstream = [inputs.refs[k] for k in (ArtifactType.INSIGHT, ArtifactType.PEER_DEFINITION, ArtifactType.COMPARISON) if k in inputs.refs]
    draft = {
        "artifact_type": "report", "schema_version": "report@1", "status": "PARTIAL" if doc.limitations else "VALID",
        "producer": {"agent": AGENT, "agent_version": AGENT_VERSION},
        "snapshot_refs": [step.snapshot_id], "semantic_config_version": step.semantic_config_version,
        "source_refs": sorted({st.source_ref.split("#", 1)[0] for st in doc.statements if st.source_ref}),
        "input_artifact_refs": [r.model_dump(mode="json") for r in [inputs.dataset_ref, *upstream, *inputs.chart_refs]],
        "limitations": doc.limitations,
        "payload": {**doc.to_payload(), "validation": validation, "delivery": {"report_id": saved["report_id"]}},
    }  # fmt: skip
    try:
        stored = await tools.call("artifact_put", {"draft_json": canonical_json(json.loads(json.dumps(draft)))})
    except Exception as exc:
        raise _Fail("failed", "TOOL_FAILED", f"artifact_put failed: {exc}") from None
    ref = ArtifactRef(artifact_id=stored["artifact_id"], version=stored["version"], artifact_type=ArtifactType.REPORT,
                      content_hash=stored["content_hash"])
    return _report(step, "completed", refs=[ref], warnings=doc.limitations, partial=bool(doc.limitations),
                   summary=f"Báo cáo {saved['report_id']}: {len(doc.statements)} số liệu kiểm chứng, {len(doc.charts)} biểu đồ,"
                           f" {len(doc.tables)} bảng.")
