"""Resolve the canonical Data inputs of a StepSpec from the Artifact Store (WS3; used by Insight and Compare).

`resolve_data_inputs(step, tools)` reads the `dataset` (re_dataset@1), `metric` (re_metric@1) and `dq` (re_dq@1)
named in `step.input_refs` through the MCP tool `artifact_get` and checks, before any analysis:

- each type is present once and pinned by `content_hash`; the stored version exists for this user and matches it;
- schema versions are the canonical ones and statuses are VALID or PARTIAL;
- every artifact carries exactly the step's snapshot and semantic config version (no substitution);
- metric and dq were derived from that very dataset (their `input_artifact_refs` pin it);
- the step's user is the calling user and every dataset row lies inside the caller's authorized projects.

Failures raise `InputError` with a code; `INPUT_ERROR_CLASSES` maps it to the Orchestrator's error class.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from vdagent_contracts.envelope import ArtifactRef, ArtifactType
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec

REQUIRED = {ArtifactType.DATASET: "re_dataset@1", ArtifactType.METRIC: "re_metric@1", ArtifactType.DQ: "re_dq@1"}

INPUT_ERROR_CLASSES: dict[str, ErrorClass] = {
    "SNAPSHOT_REQUIRED": ErrorClass.SPEC_ISSUE,
    "SEMANTIC_VERSION_REQUIRED": ErrorClass.SPEC_ISSUE,
    "MISSING_INPUT": ErrorClass.SPEC_ISSUE,
    "INPUT_HASH_REQUIRED": ErrorClass.SPEC_ISSUE,
    "INPUT_SCHEMA_UNSUPPORTED": ErrorClass.SPEC_ISSUE,
    "SNAPSHOT_MISMATCH": ErrorClass.SPEC_ISSUE,
    "SEMANTIC_VERSION_MISMATCH": ErrorClass.SPEC_ISSUE,
    "INPUT_NOT_FOUND": ErrorClass.NO_DATA,
    "INPUT_TYPE_MISMATCH": ErrorClass.WRONG_RESULT,
    "INPUT_HASH_MISMATCH": ErrorClass.WRONG_RESULT,
    "LINEAGE_MISMATCH": ErrorClass.WRONG_RESULT,
    "INPUT_INVALID": ErrorClass.DATA_QUALITY,
    "USER_CONTEXT_MISMATCH": ErrorClass.NO_ACCESS,
    "SCOPE_VIOLATION": ErrorClass.NO_ACCESS,
    "INPUT_TYPE_UNSUPPORTED": ErrorClass.SPEC_ISSUE,
}


class InputError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message

    @property
    def state(self) -> str:
        """`rejected` for a malformed request, `failed` for inputs that exist but cannot be used."""
        return "rejected" if INPUT_ERROR_CLASSES[self.code] in (ErrorClass.SPEC_ISSUE, ErrorClass.NO_ACCESS) else "failed"


class Tools(Protocol):
    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DataInputs:
    dataset: dict[str, Any]
    metric: dict[str, Any]
    dq: dict[str, Any]
    refs: list[ArtifactRef]  # dataset, metric, dq, each pinned by its stored content_hash
    authorized_project_ids: list[str]
    authorized_zone_ids: list[str]

    @property
    def limitations(self) -> list[str]:
        """Every limitation code the Data artifacts carry (to be passed on, never dropped)."""
        return sorted({code for env in (self.dataset, self.metric, self.dq) for code in env.get("limitations", [])})


def _ref(env: dict[str, Any]) -> ArtifactRef:
    return ArtifactRef(artifact_id=env["artifact_id"], version=env["version"], artifact_type=ArtifactType(env["artifact_type"]),
                       content_hash=env["content_hash"])


async def _fetch_pinned(step: StepSpec, tools: Tools, ref: ArtifactRef, kind: ArtifactType, schema: str) -> dict[str, Any]:
    """One input: pinned by hash, readable for this user, of its type/schema, usable, on the step's snapshot/semantic."""
    if ref.content_hash is None:
        raise InputError("INPUT_HASH_REQUIRED", f"input {ref.artifact_id}@{ref.version} is not pinned by content_hash")
    try:
        env = await tools.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})
    except Exception:
        raise InputError("INPUT_NOT_FOUND", f"input {ref.artifact_id}@{ref.version} is not readable") from None
    label = f"{ref.artifact_id}@{ref.version}"
    if env["artifact_type"] != kind.value:
        raise InputError("INPUT_TYPE_MISMATCH", f"{label} is {env['artifact_type']}, not {kind.value}")
    if env["content_hash"] != ref.content_hash:
        raise InputError("INPUT_HASH_MISMATCH", f"{label}: content hash does not match the stored version")
    if env["schema_version"] != schema:
        raise InputError("INPUT_SCHEMA_UNSUPPORTED", f"{label} is {env['schema_version']}, expected {schema}")
    if env["status"] not in ("VALID", "PARTIAL"):
        raise InputError("INPUT_INVALID", f"{label} has status {env['status']}")
    if env["snapshot_refs"] != [step.snapshot_id]:
        raise InputError("SNAPSHOT_MISMATCH", f"{label} is on {env['snapshot_refs']}, the step on {step.snapshot_id}")
    if env["semantic_config_version"] != step.semantic_config_version:
        raise InputError("SEMANTIC_VERSION_MISMATCH",
                         f"{label} uses {env['semantic_config_version']}, the step {step.semantic_config_version}")
    return env


async def resolve_data_inputs(step: StepSpec, tools: Tools) -> DataInputs:
    if not step.snapshot_id:
        raise InputError("SNAPSHOT_REQUIRED", "a snapshot_id is required")
    if not step.semantic_config_version:
        raise InputError("SEMANTIC_VERSION_REQUIRED", "a semantic_config_version is required")
    caller = await tools.call("get_user_context", {})
    if caller.get("user_id") != step.user_context.user_id:
        raise InputError("USER_CONTEXT_MISMATCH", "the step's user_context is not the calling user")

    envs: dict[ArtifactType, dict[str, Any]] = {}
    for kind, schema in REQUIRED.items():
        refs = [r for r in step.input_refs if r.artifact_type is kind]
        if len(refs) != 1:
            raise InputError("MISSING_INPUT", f"exactly one {kind.value} input is required, got {len(refs)}")
        envs[kind] = await _fetch_pinned(step, tools, refs[0], kind, schema)

    dataset = envs[ArtifactType.DATASET]
    pinned = _ref(dataset).model_dump(mode="json")
    for kind in (ArtifactType.METRIC, ArtifactType.DQ):
        if pinned not in envs[kind].get("input_artifact_refs", []):
            raise InputError("LINEAGE_MISMATCH", f"{kind.value} {envs[kind]['artifact_id']} was not derived from dataset {dataset['artifact_id']}")

    scope = caller.get("authorized_scope") or {}
    projects, zones = list(scope.get("project_ids") or []), list(scope.get("zone_ids") or [])
    for table, rows in (dataset.get("payload", {}).get("tables") or {}).items():
        for row in rows:
            project, zone = row.get("project_key"), row.get("zone_key")
            if project is not None and project not in projects and zone not in zones:
                raise InputError("SCOPE_VIOLATION", f"dataset {dataset['artifact_id']} holds {table} rows outside your scope")
    return DataInputs(dataset=dataset, metric=envs[ArtifactType.METRIC], dq=envs[ArtifactType.DQ],
                      refs=[_ref(envs[k]) for k in REQUIRED], authorized_project_ids=projects, authorized_zone_ids=zones)


# ---- analysis inputs (WS4: Chart; later Report) ---------------------------------------------------------------------

ANALYSIS = {ArtifactType.INSIGHT: "insight.v2", ArtifactType.COMPARISON: "comparison@1",
            ArtifactType.PEER_DEFINITION: "peer_definition@1"}
CHART_DATA = {ArtifactType.METRIC: "re_metric@1", ArtifactType.DQ: "re_dq@1", ArtifactType.EVIDENCE: "evidence@1"}


@dataclass(frozen=True)
class AnalysisInputs:
    insight: dict[str, Any] | None
    comparison: dict[str, Any] | None
    peer_definition: dict[str, Any] | None
    refs: dict[ArtifactType, ArtifactRef]  # the present inputs, pinned by their stored content_hash
    dataset_ref: ArtifactRef  # the one Data dataset every input was derived from
    authorized_project_ids: list[str]
    authorized_zone_ids: list[str]
    metrics: list[dict[str, Any]] = field(default_factory=list)
    metric_refs: list[ArtifactRef] = field(default_factory=list)
    dq: dict[str, Any] | None = None
    dq_ref: ArtifactRef | None = None
    evidences: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[ArtifactRef] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)  # chart_spec envelopes (WS6, when allowed)
    chart_refs: list[ArtifactRef] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return [k.value for k in (ArtifactType.INSIGHT, ArtifactType.COMPARISON, ArtifactType.PEER_DEFINITION) if k not in self.refs]

    @property
    def limitations(self) -> list[str]:
        envs = [e for e in (self.insight, self.comparison, self.peer_definition, self.dq,
                            *self.metrics, *self.evidences, *self.charts) if e is not None]
        return sorted({code for env in envs for code in env.get("limitations", [])})


async def resolve_analysis_inputs(step: StepSpec, tools: Tools, *, chart_specs: bool = False) -> AnalysisInputs:
    """Insight and/or Comparison (+ its PeerDefinition) of one run: pinned, same snapshot/semantic, one dataset.

    At least one of `insight` / `comparison` is required; each type at most once; any other type is rejected —
    except, with `chart_specs=True` (Report, WS6), any number of `chart_spec@1` inputs, which must pin the same dataset.
    """
    if not step.snapshot_id:
        raise InputError("SNAPSHOT_REQUIRED", "a snapshot_id is required")
    if not step.semantic_config_version:
        raise InputError("SEMANTIC_VERSION_REQUIRED", "a semantic_config_version is required")
    caller = await tools.call("get_user_context", {})
    if caller.get("user_id") != step.user_context.user_id:
        raise InputError("USER_CONTEXT_MISMATCH", "the step's user_context is not the calling user")
    kinds = [r.artifact_type for r in step.input_refs]
    if ArtifactType.INSIGHT not in kinds and ArtifactType.COMPARISON not in kinds:
        raise InputError("MISSING_INPUT", "an insight or a comparison input is required")
    allowed = {ArtifactType.DATASET, *ANALYSIS, *CHART_DATA} | ({ArtifactType.CHART_SPEC} if chart_specs else set())
    extra = sorted({k.value for k in kinds if k not in allowed})
    if extra:
        raise InputError("INPUT_TYPE_UNSUPPORTED", f"unsupported input types: {', '.join(extra)}")
    envs: dict[ArtifactType, dict[str, Any]] = {}
    dataset_refs = [r for r in step.input_refs if r.artifact_type is ArtifactType.DATASET]
    if len(dataset_refs) > 1:
        raise InputError("MISSING_INPUT", f"at most one dataset input is allowed, got {len(dataset_refs)}")
    dataset_env = await _fetch_pinned(step, tools, dataset_refs[0], ArtifactType.DATASET, "re_dataset@1") if dataset_refs else None
    for kind, schema in ANALYSIS.items():
        refs = [r for r in step.input_refs if r.artifact_type is kind]
        if len(refs) > 1:
            raise InputError("MISSING_INPUT", f"at most one {kind.value} input is allowed, got {len(refs)}")
        if refs:
            envs[kind] = await _fetch_pinned(step, tools, refs[0], kind, schema)
    metric_envs = [await _fetch_pinned(step, tools, r, ArtifactType.METRIC, CHART_DATA[ArtifactType.METRIC])
                   for r in step.input_refs if r.artifact_type is ArtifactType.METRIC]
    dq_refs = [r for r in step.input_refs if r.artifact_type is ArtifactType.DQ]
    if len(dq_refs) > 1:
        raise InputError("MISSING_INPUT", f"at most one dq input is allowed, got {len(dq_refs)}")
    dq_env = await _fetch_pinned(step, tools, dq_refs[0], ArtifactType.DQ, CHART_DATA[ArtifactType.DQ]) if dq_refs else None
    evidence_envs = [await _fetch_pinned(step, tools, r, ArtifactType.EVIDENCE, CHART_DATA[ArtifactType.EVIDENCE])
                     for r in step.input_refs if r.artifact_type is ArtifactType.EVIDENCE]

    charts = [await _fetch_pinned(step, tools, r, ArtifactType.CHART_SPEC, "chart_spec@1")
              for r in step.input_refs if r.artifact_type is ArtifactType.CHART_SPEC]
    datasets = set()
    if dataset_env is not None:
        datasets.add(json.dumps(_ref(dataset_env).model_dump(mode="json"), sort_keys=True))
    for env in [*envs.values(), *metric_envs, *([dq_env] if dq_env is not None else []), *evidence_envs, *charts]:
        found = [r for r in env.get("input_artifact_refs", []) if r.get("artifact_type") == ArtifactType.DATASET.value]
        if len(found) != 1:
            raise InputError("LINEAGE_MISMATCH", f"{env['artifact_id']} does not pin exactly one dataset")
        datasets.add(json.dumps(found[0], sort_keys=True))
    if len(datasets) != 1:
        raise InputError("LINEAGE_MISMATCH", "the inputs were derived from different datasets")
    comparison, peer_def = envs.get(ArtifactType.COMPARISON), envs.get(ArtifactType.PEER_DEFINITION)
    if comparison is not None and peer_def is not None and _ref(peer_def).model_dump(mode="json") not in comparison["input_artifact_refs"]:
        raise InputError("LINEAGE_MISMATCH", "the comparison does not pin the given peer definition")
    scope = caller.get("authorized_scope") or {}
    return AnalysisInputs(
        insight=envs.get(ArtifactType.INSIGHT), comparison=comparison, peer_definition=peer_def,
        refs={**({ArtifactType.DATASET: _ref(dataset_env)} if dataset_env is not None else {}),
              **{k: _ref(v) for k, v in envs.items()},
              **({ArtifactType.METRIC: _ref(metric_envs[0])} if len(metric_envs) == 1 else {}),
              **({ArtifactType.DQ: _ref(dq_env)} if dq_env is not None else {}),
              **({ArtifactType.EVIDENCE: _ref(evidence_envs[0])} if len(evidence_envs) == 1 else {})},
        dataset_ref=ArtifactRef.model_validate(json.loads(next(iter(datasets)))),
        authorized_project_ids=list(scope.get("project_ids") or []), authorized_zone_ids=list(scope.get("zone_ids") or []),
        metrics=metric_envs, metric_refs=[_ref(m) for m in metric_envs],
        dq=dq_env, dq_ref=_ref(dq_env) if dq_env is not None else None,
        evidences=evidence_envs, evidence_refs=[_ref(e) for e in evidence_envs],
        charts=charts, chart_refs=[_ref(c) for c in charts],
    )
