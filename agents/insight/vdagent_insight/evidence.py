"""`insight_evidence@2` (vdagent_contracts.insight_evidence): what Insight's findings stand on, typed for consumers.

Built from the engine's candidates — the deterministic output of steps 3–4 — never from the narration: an LLM decides
which slots a sentence mentions and which candidates it narrates, so neither may change what Chart draws.

Per candidate (one finding, engine order):
- every numeric slot becomes a metric: the Data dataset field it was read from (`<table>.<field>`, through the inverse
  of the DW reader's mapping) with a JSON pointer into the stored dataset whose value is checked equal to the slot's;
  a value Insight computed itself keeps no pointer and is not chartable;
- role: a DOM slot is `context`, the cause's required evidence `primary`, its supplementary evidence `supporting`;
- the DW mart's peer-relative figures are not published: Compare owns peer facts. A finding that stands on one gets a
  `target_vs_peer` intent on Compare's counterpart metric (`requires: comparison`) instead;
- chartable: a catalog metric with a verified pointer;
- visual intents: `current_value` (KPI) over the chartable context/primary metrics, plus that `target_vs_peer`.
"""

from __future__ import annotations

from typing import Any

from vdagent_contracts.envelope import ArtifactRef
from vdagent_contracts.insight_evidence import EVIDENCE_SCHEMA, METRICS, resolve_pointer, same_value

from .contracts import ArtifactEnvelope, InsightCandidate, NumericBinding, ReadArtifactRef
from .dw_reader import dataset_pointer
from .settings import SemanticConfig


def _role(candidate: InsightCandidate, slot: str, cfg: SemanticConfig) -> str:
    if slot in cfg.language.dom_slots:
        return "context"
    if candidate.cause_code in cfg.allowed_cause_codes:
        cause = cfg.cause(candidate.cause_code)
        if any(s.slot == slot for s in cause.supplementary_evidence):
            return "supporting"
    return "primary"


def _metric(binding: NumericBinding, role: str, local_dataset_id: str, view: dict[str, Any],
            dataset: dict[str, Any]) -> dict[str, Any]:
    value = str(binding.value)
    target, _, path = binding.metric_ref.partition("#")
    pointer, metric_id, reason = None, f"insight_computed.{binding.slot}", "COMPUTED_BY_INSIGHT"
    if target == local_dataset_id:
        _, table, index, field = path.split("/", 3) if path.count("/") >= 3 else ("", "", "", "")
        try:
            row = view[table][int(index)]
        except (KeyError, IndexError, ValueError):
            row = None
        found = dataset_pointer(dataset["payload"], table, row, field) if isinstance(row, dict) else None
        if found is not None and same_value(resolve_pointer(dataset["payload"], found), value):
            pointer, metric_id = found, ".".join(found.split("/")[2:5:2])
            reason = ""
        else:
            reason = "SOURCE_UNRESOLVED"
    known = METRICS.get(metric_id)
    if not reason:
        if known is None:
            reason = "NOT_IN_METRIC_CATALOG"
        elif known.unit != binding.unit:
            reason = "UNIT_MISMATCH"
    return {
        "metric_id": metric_id, "slot": binding.slot, "label": known.label if known else binding.slot,
        "value_exact": value, "unit": binding.unit, "role": role,
        "source_ref": f"{dataset['artifact_id']}@{dataset['version']}#{pointer}" if pointer else None,
        "chartable": not reason, "not_chartable_reason": reason or None,
    }


def _finding(candidate: InsightCandidate, insight_id: str | None, cfg: SemanticConfig, local_dataset_id: str,
             view: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    order = {name: i for i, name in enumerate(candidate.slots)}
    metrics, peers = [], []
    for slot, b in sorted(candidate.slots.items(), key=lambda kv: order[kv[0]]):
        m = _metric(b, _role(candidate, slot, cfg), local_dataset_id, view, dataset)
        known = METRICS.get(m["metric_id"])
        if known is not None and known.peer is not None:  # a mart peer figure: Compare's to state, not Insight's
            peers.append(known.peer.compare_metric)
            continue
        metrics.append(m)
    peers = list(dict.fromkeys(peers))
    intents: list[dict[str, Any]] = []
    kpis = [m["metric_id"] for m in metrics if m["chartable"] and m["role"] in ("context", "primary")]
    if kpis:
        intents.append({"question": "current_value", "chart_type": "kpi_card", "metric_ids": kpis, "requires": None})
    if peers:
        intents.append({"question": "target_vs_peer", "chart_type": "bar", "metric_ids": peers, "requires": "comparison"})
    return {
        "finding_id": candidate.candidate_id, "insight_id": insight_id, "insight_type": candidate.insight_type,
        "cause_code": candidate.cause_code, "level": candidate.level, "subject": candidate.subject.model_dump(mode="json"),
        "severity_rank": candidate.severity_rank,
        "attribution_score": None if candidate.attribution_score is None else str(candidate.attribution_score),
        "confidence": candidate.confidence, "metrics": metrics, "visual_intents": intents,
        "limitations": list(candidate.dq_flags),
    }


def build_evidence(*, envelope: ArtifactEnvelope, candidates: list[InsightCandidate], candidates_ref: ReadArtifactRef,
                   cfg: SemanticConfig, local_dataset_id: str, view: dict[str, Any], dataset: dict[str, Any],
                   dataset_ref: ArtifactRef, snapshot_id: str, semantic_config_version: str) -> dict[str, Any]:
    """The `evidence` block of the shared insight artifact (validate it with `parse_evidence` before storing)."""
    narrated = {i.candidate_id: i.insight_id for i in envelope.payload.insights}
    return {
        "schema_version": EVIDENCE_SCHEMA, "snapshot_id": snapshot_id, "semantic_config_version": semantic_config_version,
        "dataset_ref": dataset_ref.model_dump(mode="json"),
        "candidates_ref": {"artifact_id": candidates_ref.artifact_id, "content_hash": candidates_ref.content_hash},
        "findings": [_finding(c, narrated.get(c.candidate_id), cfg, local_dataset_id, view, dataset) for c in candidates],
    }
