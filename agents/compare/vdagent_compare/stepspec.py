"""Compare's StepSpec@1 path (WS3): canonical Data artifacts in, shared `peer_definition` + `comparison` out.

1. Validate the operation (`compare_to_peers`) and its spec (subject, comparisonMode, metricsRequested).
2. `resolve_data_inputs`: the pinned dataset / metric / dq, checked for hash, snapshot, semantic version, lineage
   and scope (vdagent_contracts.step_inputs).
3. Build the engine's `DataPackage` from the dataset — never the hero fixture or a CSV pack:
   DW TEXT keys as ids, `net_area_m2` through `peer_rules.peer_area` (D9), statuses lower-cased, metrics from the
   inventory / diagnostics rows; values the DW does not hold (discount, leads per candidate) stay None (D8).
   The area tolerance is the sc-1 ratio converted explicitly to the engine's percent (`tolerance_percent`).
   `min_peer_count` has no approved sc-1 source (B-2): it is not set, the engine applies its built-in default,
   and the artifacts say so (`BLOCKED:B-2_min_peer_count`).
4. Run the unchanged deterministic engine (`CompareService.run`) in a worker thread.
5. Store both artifacts through `artifact_put` (numbers as decimal strings, no float), pinned to the Data inputs;
   the comparison also pins the peer definition. Answer with an `AgentReport@1`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.peer_rules import PeerAreaUnavailable, area_tolerance_ratio, peer_area, tolerance_percent
from vdagent_contracts.reports import AgentReport, ReportError
from vdagent_contracts.step_inputs import INPUT_ERROR_CLASSES, DataInputs, InputError, Tools, resolve_data_inputs

from . import phrasing
from .llm import JsonLLM
from .vh_chat import render
from .vh_data import DataPackage, Unit
from .vh_service import CompareService

log = logging.getLogger(__name__)
PHRASE_TIMEOUT_S = 15.0  # the step deadline is 30 s (spec §3.4): engine + artifact_put first, one wording call after
AGENT, AGENT_VERSION = "compare", "0.3.0"
OPERATIONS = ("compare_to_peers",)
B2 = "BLOCKED:B-2_min_peer_count"
ENGINE_DEFAULT_MIN_PEERS = 5  # vh_service: approved_config.get("min_peer_count", "5")
_ENVELOPE_KEYS = {"artifact_id", "run_id", "task_id", "artifact_type", "schema_version", "version", "status", "producer",
                  "snapshot_refs", "source_refs", "input_artifact_refs", "evidence_refs", "semantic_config_version",
                  "limitations", "content_hash"}

COMPARE_ERROR_CLASSES: dict[str, ErrorClass] = {
    **INPUT_ERROR_CLASSES,
    "UNKNOWN_OPERATION": ErrorClass.SPEC_ISSUE,
    "INVALID_SPEC": ErrorClass.SPEC_ISSUE,
    "INVALID_INPUT": ErrorClass.SPEC_ISSUE,
    "SUBJECT_NOT_FOUND": ErrorClass.NO_DATA,
    "PERMISSION_DENIED": ErrorClass.NO_ACCESS,
    "SUBJECT_AMBIGUOUS": ErrorClass.NEED_INPUT,
    "CLARIFICATION_NEEDED": ErrorClass.NEED_INPUT,
    "SUBJECT_AREA_UNAVAILABLE": ErrorClass.DATA_QUALITY,
    "TOOL_FAILED": ErrorClass.TRANSIENT,
}


class _Subject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entityType: Literal["unit"] = "unit"
    entityCode: str | None = None
    entityId: str | None = None

    @model_validator(mode="after")
    def _one(self) -> _Subject:
        if not (self.entityCode or self.entityId):
            raise ValueError("subject needs entityCode or entityId")
        return self


class CompareSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: _Subject
    comparisonMode: Literal["peer_group", "head_to_head", "cohort", "ranking"] = "peer_group"
    metricsRequested: list[str] | None = None


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


def _decimals(value: Any) -> Any:
    """Engine floats → exact decimal strings (their shortest repr); ints, strings and None unchanged."""
    if isinstance(value, float):
        return str(Decimal(repr(value)))
    if isinstance(value, dict):
        return {k: _decimals(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decimals(v) for v in value]
    return value


def _number(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def build_package(inputs: DataInputs) -> tuple[DataPackage, dict[str, Any]]:
    """The engine's package from the canonical dataset; also returns the tolerance record for the artifacts."""
    payload = inputs.dataset["payload"]
    tables = payload["tables"]
    config = payload.get("semantic_config", {})
    tolerance = config.get("peer_area_tolerance_pct")
    if tolerance is None:
        raise _Fail("failed", "INVALID_INPUT", "the dataset carries no peer_area_tolerance_pct")
    ratio = area_tolerance_ratio(tolerance["value"])
    inventory = {r["unit_key"]: r for r in tables["fact_unit_inventory_snapshot"]}
    diagnostics = {r["unit_key"]: r for r in tables["dm_unit_friction_diagnostics"]}
    units = []
    for u in tables["dim_unit_master"]:
        inv = inventory.get(u["unit_key"])
        if inv is None:
            continue  # no row at this snapshot: not a unit of this snapshot
        try:
            area = peer_area(u)
        except PeerAreaUnavailable:
            continue  # Data already excludes these candidates; never fall back to area_m2
        dom = _number(inv["unsold_days_dom"])
        diag = diagnostics.get(u["unit_key"]) or {}
        units.append(Unit(
            unit_id=u["unit_key"], unit_code=u["unit_code"], project_id=u["project_key"], zone_id=u["zone_key"],
            unit_type=u["unit_type"], area_m2=area, floor_band=u["floor_band"], balcony_orientation=u["balcony_orientation"],
            view_type=u["view_primary_type"], status=inv["inventory_status"].lower(), launch_batch_id=u["launch_batch_id"],
            metrics={
                "net_asking_price_per_m2": _number(inv["net_price_per_m2"]), "asking_price_per_m2": None,
                "asking_price_vnd": _number(inv["asking_price_vnd"]), "dom": dom, "unsold_days": dom,
                "inquiry_leads_30d": None, "discount_pct": None, "subsidy_duration_mo": _number(diag.get("subsidy_duration_mo")),
            },
        ))  # fmt: skip
    approved = {"peer_area_tolerance_pct": str(tolerance_percent(ratio))}
    overdue = config.get("overdue_threshold_days")
    if overdue is not None:
        approved["overdue_threshold_days"] = str(overdue["value"])
    snap = payload["snapshot"]
    package = DataPackage(
        name="re_warehouse", snapshot_id=snap["snapshot_id"], semantic_version=snap["semantic_config_version"],
        snapshot_date=snap["snapshot_date"], metric_artifact_id=inputs.metric["artifact_id"],
        dq_artifact_id=inputs.dq["artifact_id"], units=tuple(units), approved_config=approved,
    )
    record = {"ratio": str(ratio), "percent": str(tolerance_percent(ratio).quantize(Decimal("0.01"))),
              "source": "semantic_config[sc-1].peer_area_tolerance_pct"}
    return package, record


async def run_step(step: StepSpec, tools: Tools, llm: JsonLLM | None = None) -> AgentReport:
    try:
        return await _run(step, tools, llm)
    except InputError as exc:
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message))
    except _Fail as exc:
        retryable = COMPARE_ERROR_CLASSES.get(exc.code) is ErrorClass.TRANSIENT
        return _report(step, exc.state, error=ReportError(code=exc.code, message=exc.message, retryable=retryable))


async def _run(step: StepSpec, tools: Tools, llm: JsonLLM | None) -> AgentReport:
    if step.operation not in OPERATIONS:
        raise _Fail("rejected", "UNKNOWN_OPERATION", f"compare serves {', '.join(OPERATIONS)}, not {step.operation!r}")
    try:
        spec = CompareSpec.model_validate(step.spec)
    except ValidationError as exc:
        raise _Fail("rejected", "INVALID_SPEC", f"invalid compare_to_peers spec: {exc.error_count()} error(s)") from None
    inputs = await resolve_data_inputs(step, tools)
    package, tolerance = build_package(inputs)

    raw: dict[str, Any] = {
        "subject": spec.subject.model_dump(exclude_none=True), "comparisonMode": spec.comparisonMode,
        "scope": {"userId": step.user_context.user_id, "allowedProjectIds": inputs.authorized_project_ids,
                  "allowedZoneIds": inputs.authorized_zone_ids},
        "snapshot_id": step.snapshot_id, "semantic_config_version": step.semantic_config_version,
        "run_id": step.run_id, "task_id": step.idempotency_key,
        "input_artifact_refs": {"metricArtifactId": inputs.metric["artifact_id"], "dqArtifactId": inputs.dq["artifact_id"]},
    }  # fmt: skip
    if spec.metricsRequested:
        raw["metricsRequested"] = spec.metricsRequested
    result = await asyncio.to_thread(CompareService(package=package).run, raw)
    comparison, peer_def = result["comparison"], result.get("peer_definition")
    if comparison.get("status") == "INVALID" or peer_def is None:
        code = str(comparison.get("reason_code") or "INVALID_INPUT")
        klass = COMPARE_ERROR_CLASSES.get(code, ErrorClass.FATAL)
        state: Literal["rejected", "failed"] = "rejected" if klass is ErrorClass.SPEC_ISSUE else "failed"
        raise _Fail(state, code, str(comparison.get("reason") or code))

    limitations = sorted(set(inputs.limitations) | {B2})
    min_peers = {"value": ENGINE_DEFAULT_MIN_PEERS, "source": "engine default; sc-1 has no approved min_peer_count (B-2)"}
    dataset_ref = inputs.refs[0]

    def body(artifact: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in artifact.items() if k not in _ENVELOPE_KEYS}
        return {**_decimals(out), "engineArtifactId": artifact["artifact_id"], "engineContentHash": artifact["content_hash"],
                "engineLimitations": list(artifact.get("limitations") or []), "areaTolerance": tolerance,
                "minPeerCount": min_peers}

    async def put(kind: ArtifactType, schema: str, payload: dict[str, Any], status: str, refs: list[ArtifactRef]) -> ArtifactRef:
        draft = {
            "artifact_type": kind.value, "schema_version": schema, "status": status if status in ("VALID", "PARTIAL") else "PARTIAL",
            "producer": {"agent": AGENT, "agent_version": AGENT_VERSION},
            "snapshot_refs": [step.snapshot_id], "semantic_config_version": step.semantic_config_version,
            "source_refs": ["re:dim_unit_master", "re:fact_unit_inventory_snapshot"],
            "input_artifact_refs": [r.model_dump(mode="json") for r in refs], "limitations": limitations, "payload": payload,
        }  # fmt: skip
        try:
            stored = await tools.call("artifact_put", {"draft_json": canonical_json(json.loads(json.dumps(draft), parse_float=Decimal))})
        except Exception as exc:
            raise _Fail("failed", "TOOL_FAILED", f"artifact_put failed: {exc}") from None
        return ArtifactRef(artifact_id=stored["artifact_id"], version=stored["version"], artifact_type=kind,
                           content_hash=stored["content_hash"])

    status = "PARTIAL"  # limitations always include B-2 while it is open
    pd_ref = await put(ArtifactType.PEER_DEFINITION, "peer_definition@1", body(peer_def), status, list(inputs.refs))
    cmp_payload = body(comparison)
    subject = next((u for u in package.units if u.unit_id == peer_def.get("subject", {}).get("entityId")
                    or u.unit_code.upper() == str(spec.subject.entityCode or "").upper()), None)
    cmp_payload["subject"] = {"entityType": "unit", "entityId": subject.unit_id if subject else None,
                              "entityCode": subject.unit_code if subject else spec.subject.entityCode}
    for row in cmp_payload.get("metrics", []):
        if isinstance(row.get("sourceRef"), dict):
            row["sourceRef"] = {**row["sourceRef"], "artifactId": dataset_ref.artifact_id, "version": dataset_ref.version}
    cmp_ref = await put(ArtifactType.COMPARISON, "comparison@1", cmp_payload, status, [*inputs.refs, pd_ref])
    peers = len(peer_def.get("peers") or [])
    sufficiency = comparison.get("dataSufficiency") or {}
    limits = sufficiency.get("summary") if sufficiency.get("level") in {"LIMITED", "INSUFFICIENT"} else ""
    template = f"So sánh {cmp_payload['subject']['entityCode']} với {peers} căn tương đồng @ {step.snapshot_id}."
    narration = await _narrate(llm, step.original_question or "", result)
    summary = " ".join(part for part in (limits, template, narration) if part)
    return _report(step, "completed", refs=[pd_ref, cmp_ref], warnings=limitations, partial=True, summary=summary)


async def _narrate(llm: JsonLLM | None, question: str, result: dict[str, Any]) -> str:
    """The model's checked sentence (after the code's own limits sentence), or "" — never an error.

    Only the report summary carries it: the stored artifacts hold engine numbers and stay deterministic.
    """
    comparison = result["comparison"]
    if llm is None or comparison.get("clarification") or comparison.get("reason_code") == "INSUFFICIENT_EVIDENCE":
        return ""  # nothing to word: no model, a question, or "not enough data" (said by the engine)
    try:
        facts = phrasing.facts_from(render(result))
        async with asyncio.timeout(PHRASE_TIMEOUT_S):
            return await phrasing.phrase(llm, question, facts) or ""
    except Exception as exc:  # narration is optional; CancelledError still propagates
        log.warning("compare: model unusable for this step, template summary kept: %r", exc)
        return ""
