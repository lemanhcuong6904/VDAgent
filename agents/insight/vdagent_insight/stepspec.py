"""Insight's StepSpec@1 path (WS3): canonical Data artifacts in, one shared `insight` artifact out.

1. Validate the operation (`explain_unit`) and its spec (intent, tasks, analysis_scope).
2. `resolve_data_inputs`: read the pinned dataset / metric / dq from the Artifact Store and check hashes, snapshot,
   semantic version, lineage and the caller's scope (vdagent_contracts.step_inputs).
3. Load the semantic config of the step's version (`sc-1` → config/semantic_insight.sc-1.yaml, D3).
4. Run the unchanged pipeline (`run_task`) over `DwArtifactReader` — no export pack, no fixture; TEMPLATE unless
   LLM providers are configured.
5. Store the result through `artifact_put` as `insight` / `insight.v2`, pinned to the Data inputs, with the Data
   limitations carried forward (D8), and answer with an `AgentReport@1`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport, ReportError
from vdagent_contracts.step_inputs import INPUT_ERROR_CLASSES, InputError, Tools, resolve_data_inputs

from .agent import AGENT_VERSION, EventSink, InsightDeps, run_task
from .contracts import AnalysisScope, Intent, TaskCode
from .dw_reader import DwArtifactReader, store_id
from .llm.steps import LlmProviders
from .memory import NoOpMemory
from .runtime import as_of_from, local_now
from .settings import ConfigError, LlmConfig, SemanticConfigRegistry
from .store import InsightStore

AGENT = "insight"
OPERATIONS = ("explain_unit",)
ID_NAMESPACE = uuid.UUID("6f1d8c9e-2b7a-4c55-9e0f-3a1b2c4d5e6f")

INSIGHT_ERROR_CLASSES: dict[str, ErrorClass] = {
    **INPUT_ERROR_CLASSES,
    "UNKNOWN_OPERATION": ErrorClass.SPEC_ISSUE,
    "INVALID_SPEC": ErrorClass.SPEC_ISSUE,
    "SEMANTIC_CONFIG_UNKNOWN": ErrorClass.SPEC_ISSUE,
    "E02": ErrorClass.WRONG_RESULT,  # input artifact unreadable / inconsistent (pipeline step 1)
    "E03": ErrorClass.SPEC_ISSUE,  # snapshot / semantic version unknown to Insight
    "E04": ErrorClass.NO_ACCESS,  # analysis scope outside the authorized scope
    "TOOL_FAILED": ErrorClass.TRANSIENT,
    "INTERNAL_ERROR": ErrorClass.FATAL,
}


def _no_events(event: str, fields: dict[str, Any]) -> None:
    return None


@dataclass(frozen=True)
class StepEnv:
    registry: SemanticConfigRegistry
    llm: LlmConfig
    store: InsightStore
    providers: LlmProviders | None = None  # None → TEMPLATE
    events: EventSink = field(default=_no_events)
    clock: Callable[[], datetime] = local_now
    role: str = "SALES_OPS"


class ExplainSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent
    tasks: list[TaskCode] = Field(min_length=1)
    analysis_scope: AnalysisScope


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


async def run_step(step: StepSpec, tools: Tools, env: StepEnv) -> AgentReport:
    try:
        return await _run(step, tools, env)
    except InputError as exc:
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message))
    except _Fail as exc:
        retryable = INSIGHT_ERROR_CLASSES.get(exc.code) is ErrorClass.TRANSIENT
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message, retryable=retryable))


async def _run(step: StepSpec, tools: Tools, env: StepEnv) -> AgentReport:
    if step.operation not in OPERATIONS:
        raise _Fail("rejected", "UNKNOWN_OPERATION", f"insight serves {', '.join(OPERATIONS)}, not {step.operation!r}")
    try:
        spec = ExplainSpec.model_validate(step.spec)
    except ValidationError as exc:
        raise _Fail("rejected", "INVALID_SPEC", f"invalid explain_unit spec: {exc.error_count()} error(s)") from None

    inputs = await resolve_data_inputs(step, tools)
    scope = spec.analysis_scope
    if not set(scope.project_ids) <= set(inputs.authorized_project_ids):
        raise _Fail("rejected", "SCOPE_VIOLATION", "the analysis scope names a project outside your authorized scope")
    try:
        cfg = env.registry.get(step.semantic_config_version or "")
    except ConfigError:
        raise _Fail("rejected", "SEMANTIC_CONFIG_UNKNOWN", f"no Insight config for {step.semantic_config_version}") from None

    reader = DwArtifactReader(inputs, cfg)
    manifest = await reader.manifest()
    artifacts = await reader.prepare_required(scope)
    request = {
        "run_id": str(uuid.uuid5(ID_NAMESPACE, f"run:{step.run_id}")),
        "task_id": str(uuid.uuid5(ID_NAMESPACE, f"insight:{step.idempotency_key}")),
        "attempt": 1, "fencing_token": 1, "intent": spec.intent, "tasks": list(spec.tasks),
        "question_normalized": step.original_question[:1000], "analysis_scope": scope.model_dump(mode="json"),
        "snapshot_id": step.snapshot_id, "semantic_config_version": step.semantic_config_version,
        "user_context": {"user_id": step.user_context.user_id, "role": env.role,
                         "authorized_scope": {"project_ids": inputs.authorized_project_ids, "zone_ids": inputs.authorized_zone_ids}},
        "input_artifact_refs": [{"artifact_id": a.artifact_id, "artifact_type": a.artifact_type, "version": a.version,
                                 "status": a.status, "content_hash": a.content_hash} for a in artifacts],
    }  # fmt: skip
    from .contracts import InsightTaskRequest

    deps = InsightDeps(
        reader=reader, registry=env.registry, llm=env.llm, store=env.store, usage=env.store, memory=NoOpMemory(),
        providers=env.providers, clock=env.clock, events=env.events, as_of=as_of_from({}, manifest.snapshot_date),
    )  # fmt: skip
    result = await run_task(InsightTaskRequest.model_validate(request), deps)
    if result.envelope is None:
        code = result.error_code or "INTERNAL_ERROR"
        klass = INSIGHT_ERROR_CLASSES.get(code, ErrorClass.FATAL)
        state: Literal["rejected", "failed"] = "rejected" if klass in (ErrorClass.SPEC_ISSUE, ErrorClass.NO_ACCESS) else "failed"
        raise _Fail(state, code, result.error_message or "insight task failed")

    envelope = result.envelope
    by_id = {r.artifact_id: r for r in inputs.refs}
    evidence = sorted({store_id(e.split("#", 1)[0]) for e in envelope.evidence_refs} & set(by_id))
    local_limits = [lim.code for lim in envelope.limitations]
    limitations = sorted(set(inputs.limitations) | set(local_limits) | {"FIELD_UNAVAILABLE:asking_price_per_m2"})
    status = "PARTIAL" if envelope.status == "PARTIAL" or limitations else envelope.status
    view = next(a for a in artifacts if a.artifact_type == "dataset").payload
    draft = {
        "artifact_type": "insight", "schema_version": "insight.v2", "status": status,
        "producer": {"agent": AGENT, "agent_version": AGENT_VERSION, "prompt_version": envelope.producer.prompt_version,
                     "model_id": envelope.producer.model_id},
        "snapshot_refs": [step.snapshot_id], "semantic_config_version": step.semantic_config_version,
        "source_refs": [f"insight:{envelope.artifact_id}"],
        "input_artifact_refs": [r.model_dump(mode="json") for r in inputs.refs],
        "evidence_refs": [by_id[i].model_dump(mode="json") for i in evidence],
        "limitations": limitations,
        "payload": {
            "insight": envelope.payload.model_dump(mode="json"),
            "input_view": view,
            "local_artifact": {"artifact_id": envelope.artifact_id, "content_hash": envelope.content_hash,
                               "evidence_refs": list(envelope.evidence_refs),
                               "limitations": [lim.model_dump(mode="json") for lim in envelope.limitations]},
            "request": {"intent": spec.intent, "tasks": list(spec.tasks), "analysis_scope": scope.model_dump(mode="json")},
        },
    }  # fmt: skip
    try:
        stored = await tools.call("artifact_put", {"draft_json": canonical_json(json.loads(json.dumps(draft)))})
    except Exception as exc:
        raise _Fail("failed", "TOOL_FAILED", f"artifact_put failed: {exc}") from None
    ref = ArtifactRef(artifact_id=stored["artifact_id"], version=stored["version"], artifact_type=ArtifactType.INSIGHT,
                      content_hash=stored["content_hash"])
    insights = envelope.payload.insights
    summary = f"Insight {status}: {len(insights)} insight trên {manifest.snapshot_id} ({envelope.payload.summary.narrative_mode})."
    return _report(step, "completed", refs=[ref], warnings=limitations, partial=status == "PARTIAL", summary=summary)
