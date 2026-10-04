"""Isolated Chart evaluation harness.

This module builds canonical upstream artifacts without running Data, Insight or
Compare, then feeds them to the same `StepSpec@1 -> run_step` Chart path used by
production orchestration. It is local/dev evaluation support only: upstream
artifacts live in an in-memory store and are marked as synthetic upstream for
Chart evaluation.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from vdagent_contracts.insight_evidence import EVIDENCE_SCHEMA
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport

from .stepspec import run_step

ALICE = "u_000000000001"
SNAPSHOT = "SNAP-20260630-01"
SEMANTIC = "3.1.0"
LIMITATION = "SYNTHETIC_UPSTREAM_FOR_CHART_EVALUATION"
UNIT_CODE = re.compile(r"\b([A-Z]{2,4}-U\d{3,6})\b")
REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_PLAN_METRICS = ("dom", "net_asking_price_per_m2")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ref(env: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": env["artifact_id"],
        "version": env["version"],
        "artifact_type": env["artifact_type"],
        "content_hash": env["content_hash"],
    }


def _as_int(value: Any) -> int:
    return int(Decimal(str(value)))


def _median(values: list[int]) -> int | str:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    exact = (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal(2)
    return int(exact) if exact == exact.to_integral_value() else str(exact)


def _pct_gap(subject: int, benchmark: int | str) -> str:
    base = Decimal(str(benchmark))
    return str(((Decimal(subject) - base) / base * Decimal(100)).quantize(Decimal("0.01"))) if base else "0.00"


class IsolatedArtifactTools:
    """Tiny Artifact Store + user-context port for Chart StepSpec evaluation."""

    def __init__(self, *, user_id: str = ALICE, project_ids: tuple[str, ...] = ("400",)) -> None:
        self.user_id = user_id
        self.project_ids = project_ids
        self.artifacts: dict[tuple[str, int], dict[str, Any]] = {}
        self.calls: list[str] = []
        self._n = 0

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        if name == "get_user_context":
            return {"user_id": self.user_id, "authorized_scope": {"project_ids": list(self.project_ids), "zone_ids": []}}
        if name == "artifact_get":
            key = (args["artifact_id"], int(args.get("version") or self._latest(args["artifact_id"])))
            if key not in self.artifacts:
                raise LookupError(f"artifact {key[0]}@{key[1]} not found")
            return copy.deepcopy(self.artifacts[key])
        if name == "artifact_put":
            return self.put(json.loads(args["draft_json"]), run_id=args.get("run_id"))
        raise AssertionError(f"unexpected evaluation tool {name}")

    def _latest(self, artifact_id: str) -> int:
        return max((version for aid, version in self.artifacts if aid == artifact_id), default=1)

    def put(self, draft: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        self._n += 1
        artifact_id = draft.pop("artifact_id", None) or f"mock_art_{self._n:04d}"
        version = self._latest(artifact_id) + 1 if any(aid == artifact_id for aid, _ in self.artifacts) else 1
        env = {
            **draft,
            "artifact_id": artifact_id,
            "version": version,
            "run_id": run_id or draft.get("run_id") or "t_chart_eval",
            "task_id": run_id or draft.get("task_id") or "t_chart_eval",
        }
        env.setdefault("snapshot_refs", [SNAPSHOT])
        env.setdefault("semantic_config_version", SEMANTIC)
        env.setdefault("input_artifact_refs", [])
        env.setdefault("source_refs", [])
        env.setdefault("evidence_refs", [])
        env.setdefault("limitations", [])
        env["content_hash"] = _hash({k: v for k, v in env.items() if k != "content_hash"})
        self.artifacts[(artifact_id, version)] = env
        return copy.deepcopy(env)


@dataclass(frozen=True)
class UpstreamSimulationPlan:
    question: str
    subject_unit_code: str
    mode: str = "mock_real_data"
    metrics: tuple[str, ...] = ("dom", "net_asking_price_per_m2")
    peer_count: int = 4
    planner: str = "deterministic"
    repair_notes: tuple[str, ...] = ()


class UpstreamPlanReasoner(Protocol):
    async def plan_upstream_simulation(self, question: str, allowed_metrics: tuple[str, ...]) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class _UnitBundle:
    subject: dict[str, Any]
    peers: list[dict[str, Any]]
    project_id: str
    source_refs: list[str]


@dataclass(frozen=True)
class IndependentEvaluation:
    step: StepSpec
    tools: IsolatedArtifactTools
    manifest: dict[str, Any]
    upstream_refs: list[dict[str, Any]]


@dataclass(frozen=True)
class EvaluationRun:
    name: str
    experiment: IndependentEvaluation
    report: AgentReport


@dataclass(frozen=True)
class EvaluationSuite:
    name: str
    runs: list[EvaluationRun]
    report_ref: str
    report: dict[str, Any]


AblationMode = Literal["none", "no_peer_values"]


def plan_upstream_simulation(question: str, *, default_subject: str = "MAS-U00283") -> UpstreamSimulationPlan:
    """Deterministic baseline plan; LLM output is optional and still repaired into this shape."""
    found = UNIT_CODE.findall(question.upper())
    return UpstreamSimulationPlan(question=question, subject_unit_code=found[0] if found else default_subject)


def repair_upstream_simulation_plan(
    question: str,
    candidate: dict[str, Any] | None,
    *,
    default_subject: str = "MAS-U00283",
    planner: str = "llm",
) -> UpstreamSimulationPlan:
    """Whitelist and repair an LLM plan without accepting generated facts or chart specs."""
    fallback = plan_upstream_simulation(question, default_subject=default_subject)
    notes: list[str] = []
    value = candidate if isinstance(candidate, dict) else {}
    if not value:
        return UpstreamSimulationPlan(
            question=question,
            subject_unit_code=fallback.subject_unit_code,
            mode=fallback.mode,
            metrics=fallback.metrics,
            peer_count=fallback.peer_count,
            planner="deterministic_fallback" if planner == "llm" else planner,
            repair_notes=("planner_empty",),
        )

    raw_subject = str(value.get("subject_unit_code") or value.get("unit_code") or fallback.subject_unit_code).upper()
    subject_match = UNIT_CODE.search(raw_subject)
    subject = subject_match.group(1) if subject_match else fallback.subject_unit_code
    if subject != raw_subject:
        notes.append("subject_unit_code_repaired")

    raw_metrics = value.get("metrics")
    if isinstance(raw_metrics, str):
        raw_metrics = [raw_metrics]
    metrics = tuple(metric for metric in (raw_metrics or fallback.metrics) if metric in ALLOWED_PLAN_METRICS)
    if not metrics:
        metrics = fallback.metrics
        notes.append("metrics_repaired")
    elif tuple(raw_metrics or ()) != metrics:
        notes.append("metrics_repaired")

    try:
        peer_count = int(value.get("peer_count", fallback.peer_count))
    except (TypeError, ValueError):
        peer_count = fallback.peer_count
        notes.append("peer_count_repaired")
    clamped = max(2, min(12, peer_count))
    if clamped != peer_count:
        notes.append("peer_count_clamped")

    mode = str(value.get("mode") or fallback.mode)
    if mode not in {"mock_real_data", "golden"}:
        mode = fallback.mode
        notes.append("mode_repaired")

    return UpstreamSimulationPlan(
        question=question,
        subject_unit_code=subject,
        mode=mode,
        metrics=metrics,
        peer_count=clamped,
        planner=planner,
        repair_notes=tuple(notes),
    )


async def plan_upstream_simulation_with_repair(
    question: str,
    *,
    reasoner: UpstreamPlanReasoner | None = None,
    default_subject: str = "MAS-U00283",
) -> UpstreamSimulationPlan:
    if reasoner is None:
        base = plan_upstream_simulation(question, default_subject=default_subject)
        return UpstreamSimulationPlan(
            question=base.question,
            subject_unit_code=base.subject_unit_code,
            mode=base.mode,
            metrics=base.metrics,
            peer_count=base.peer_count,
            planner="deterministic",
            repair_notes=(),
        )
    try:
        candidate = await reasoner.plan_upstream_simulation(question, ALLOWED_PLAN_METRICS)
    except Exception:
        candidate = None
    return repair_upstream_simulation_plan(question, candidate, default_subject=default_subject, planner="llm")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_real_unit_bundle(plan: UpstreamSimulationPlan, *, root: Path = REPO_ROOT) -> _UnitBundle | None:
    warehouse = root / "warehouse"
    for project_dir in sorted(warehouse.glob("project_*")):
        units_path = project_dir / "dim_unit_master.csv"
        inventory_path = project_dir / "fact_unit_inventory_snapshot.csv"
        if not units_path.is_file() or not inventory_path.is_file():
            continue
        units = _read_csv(units_path)
        subject_unit = {row.get("unit_code"): row for row in units}.get(plan.subject_unit_code)
        if subject_unit is None:
            continue
        inv_rows = [
            row for row in _read_csv(inventory_path)
            if row.get("snapshot_date_key") == "20260630" and row.get("inventory_status") == "AVAILABLE"
        ]
        by_key = {row.get("unit_key"): row for row in inv_rows}
        subject_inv = by_key.get(subject_unit["unit_key"])
        if subject_inv is None:
            continue
        peer_units = [
            unit for unit in units
            if unit.get("unit_key") != subject_unit.get("unit_key")
            and unit.get("unit_type") == subject_unit.get("unit_type")
            and unit.get("unit_key") in by_key
        ]
        peer_units.sort(key=lambda unit: _as_int(by_key[unit["unit_key"]]["unsold_days_dom"]), reverse=True)
        peers = [{"unit": unit, "inventory": by_key[unit["unit_key"]]} for unit in peer_units[:plan.peer_count]]
        if len(peers) < 2:
            continue
        return _UnitBundle(
            subject={"unit": subject_unit, "inventory": subject_inv},
            peers=peers,
            project_id=str(subject_unit["project_key"]),
            source_refs=[
                str(units_path.relative_to(root)).replace("\\", "/"),
                str(inventory_path.relative_to(root)).replace("\\", "/"),
            ],
        )
    return None


def _fallback_unit_bundle(plan: UpstreamSimulationPlan) -> _UnitBundle:
    subject_key = f"U-400-{plan.subject_unit_code}"
    peers = [
        ("MAS-U00218", "U-400-MAS-U00218", 2010, 58408637),
        ("MAS-U00366", "U-400-MAS-U00366", 1984, 60135585),
        ("MAS-U00432", "U-400-MAS-U00432", 1902, 61942131),
        ("MAS-U00070", "U-400-MAS-U00070", 2071, 62654427),
    ]

    def unit(code: str, key: str, i: int) -> dict[str, str]:
        return {"unit_key": key, "unit_code": code, "project_key": "400", "zone_key": "401",
                "unit_type": "3PN", "net_area_m2": "86.10", "floor_number": str(20 + i), "floor_band": "HIGH"}

    def inv(key: str, dom: int, price: int) -> dict[str, str]:
        return {"unit_key": key, "snapshot_date_key": "20260630", "project_key": "400", "zone_key": "401",
                "inventory_status": "AVAILABLE", "unsold_days_dom": str(dom), "net_price_per_m2": str(price)}

    return _UnitBundle(
        subject={"unit": unit(plan.subject_unit_code, subject_key, 8), "inventory": inv(subject_key, 2071, 63115036)},
        peers=[{"unit": unit(code, key, i), "inventory": inv(key, dom, price)} for i, (code, key, dom, price) in enumerate(peers)],
        project_id="400",
        source_refs=["fallback:chart_independent_eval"],
    )


def _project_dataset(bundle: _UnitBundle, subject_unit_code: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [bundle.subject, *bundle.peers]
    subject_key = str(bundle.subject["unit"]["unit_key"])
    units = [
        {"unit_key": str(item["unit"]["unit_key"]), "unit_code": str(item["unit"]["unit_code"]),
         "project_key": str(item["unit"]["project_key"]), "zone_key": str(item["unit"]["zone_key"]),
         "unit_type": str(item["unit"].get("unit_type") or ""), "net_area_m2": str(item["unit"].get("net_area_m2") or ""),
         "floor_no": _as_int(item["unit"].get("floor_number") or item["unit"].get("floor_no") or 0),
         "floor_band": str(item["unit"].get("floor_band") or "")}
        for item in rows
    ]
    inventory = [
        {"unit_key": str(item["inventory"]["unit_key"]), "snapshot_date_key": 20260630,
         "project_key": str(item["inventory"]["project_key"]), "zone_key": str(item["inventory"]["zone_key"]),
         "inventory_status": str(item["inventory"]["inventory_status"]),
         "unsold_days_dom": _as_int(item["inventory"]["unsold_days_dom"]),
         "net_price_per_m2": _as_int(item["inventory"]["net_price_per_m2"])}
        for item in rows
    ]
    if units[0]["unit_code"] != subject_unit_code or inventory[0]["unit_key"] != subject_key:
        raise ValueError("subject row is not first in the evaluation dataset")
    return subject_key, units, inventory


def _artifact(
    tools: IsolatedArtifactTools,
    *,
    artifact_id: str,
    artifact_type: str,
    schema_version: str,
    producer: str,
    payload: dict[str, Any],
    input_refs: list[dict[str, Any]] | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    return tools.put({
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": schema_version,
        "status": "VALID",
        "producer": {"agent": producer, "agent_version": "mock-upstream-eval-1"},
        "snapshot_refs": [SNAPSHOT],
        "semantic_config_version": SEMANTIC,
        "source_refs": source_refs or [],
        "input_artifact_refs": input_refs or [],
        "limitations": [LIMITATION],
        "payload": payload,
    })


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _validate_grounding(tools: IsolatedArtifactTools, refs: list[dict[str, Any]]) -> dict[str, int]:
    envs = {ref["artifact_type"]: tools.artifacts[(ref["artifact_id"], ref["version"])] for ref in refs}
    dataset = envs["dataset"]
    dataset_ref = _ref(dataset)
    for kind in ("metric", "dq", "evidence", "insight", "comparison", "peer_definition"):
        if kind in envs and dataset_ref not in envs[kind]["input_artifact_refs"]:
            raise ValueError(f"{kind} does not pin the dataset")
    evidence = envs["insight"]["payload"]["evidence"]
    if evidence["dataset_ref"] != dataset_ref:
        raise ValueError("insight evidence does not pin the dataset")
    checked = 0
    for finding in evidence["findings"]:
        for metric in finding["metrics"]:
            ref, pointer = metric["source_ref"].split("#", 1)
            if ref != f"{dataset['artifact_id']}@{dataset['version']}":
                raise ValueError("insight metric source_ref points outside the dataset")
            if str(_resolve_pointer(dataset["payload"], pointer)) != str(metric["value_exact"]):
                raise ValueError("insight metric value is not grounded")
            checked += 1
    comparison = envs["comparison"]
    if _ref(envs["peer_definition"]) not in comparison["input_artifact_refs"]:
        raise ValueError("comparison does not pin peer_definition")
    inventory = {row["unit_key"]: row for row in dataset["payload"]["tables"]["fact_unit_inventory_snapshot"]}
    fields = {"dom": "unsold_days_dom", "net_asking_price_per_m2": "net_price_per_m2"}
    for row in comparison["payload"]["peerValues"]:
        source = inventory[row["entityId"]]
        for metric, field in fields.items():
            if str(source[field]) != str(row["values"][metric]):
                raise ValueError(f"{row['entityCode']}/{metric} is not grounded")
            checked += 1
    return {"artifact_count": len(refs), "grounded_values": checked}


def build_independent_evaluation(
    question: str,
    *,
    subject_unit_code: str | None = None,
    ablation: AblationMode = "none",
    simulation_plan: UpstreamSimulationPlan | None = None,
) -> IndependentEvaluation:
    """Build canonical mock-real-data artifacts and a Chart StepSpec over an isolated store."""
    plan = simulation_plan or plan_upstream_simulation(question, default_subject=subject_unit_code or "MAS-U00283")
    bundle = _load_real_unit_bundle(plan) or _fallback_unit_bundle(plan)
    tools = IsolatedArtifactTools(project_ids=(bundle.project_id,))
    run_id = "t_chart_eval_" + hashlib.sha256(f"{question}|{plan.subject_unit_code}".encode()).hexdigest()[:10]
    plan_id = "pl_chart_eval"
    subject_key, units, inventory = _project_dataset(bundle, plan.subject_unit_code)
    subject_dom = inventory[0]["unsold_days_dom"]
    subject_price = inventory[0]["net_price_per_m2"]
    peer_rows = inventory[1:]
    peer_codes = [row["unit_code"] for row in units[1:]]
    peer_dom = _median([row["unsold_days_dom"] for row in peer_rows])
    peer_price = _median([row["net_price_per_m2"] for row in peer_rows])
    dataset_payload = {
        "population": {"subject_unit_key": subject_key, "rule": "mock_real_data_chart_eval"},
        "tables": {"dim_unit_master": units, "fact_unit_inventory_snapshot": inventory},
    }
    dataset = _artifact(tools, artifact_id="mock_dataset_chart_eval", artifact_type="dataset", schema_version="re_dataset@1",
                        producer="mock_upstream_llm", payload=dataset_payload, source_refs=bundle.source_refs)
    dataset_ref = _ref(dataset)
    metric = _artifact(
        tools,
        artifact_id="mock_metric_chart_eval",
        artifact_type="metric",
        schema_version="re_metric@1",
        producer="mock_upstream_llm",
        input_refs=[dataset_ref],
        payload={"grain": "unit", "metrics": [
            {"metric_id": "dom", "source_ref": "re:fact_unit_inventory_snapshot.unsold_days_dom", "unit": "DAY",
             "subject": plan.subject_unit_code, "statistic": "current", "value": str(subject_dom), "status": "VALID"},
            {"metric_id": "net_asking_price_per_m2", "source_ref": "re:fact_unit_inventory_snapshot.net_price_per_m2",
             "unit": "VND_PER_M2", "subject": plan.subject_unit_code, "statistic": "current",
             "value": str(subject_price), "status": "VALID"},
        ]},
    )
    dq = _artifact(tools, artifact_id="mock_dq_chart_eval", artifact_type="dq", schema_version="re_dq@1",
                   producer="mock_upstream_llm", input_refs=[dataset_ref],
                   payload={"checks": [{"check_id": "grounding", "status": "PASS", "rows_checked": len(inventory)}]})
    evidence = _artifact(
        tools,
        artifact_id="mock_evidence_chart_eval",
        artifact_type="evidence",
        schema_version="evidence@1",
        producer="mock_upstream_llm",
        input_refs=[dataset_ref],
        payload={"evidence": [
            {"evidence_id": "ev_dom_subject", "metric_ids": ["fact_unit_inventory_snapshot.unsold_days_dom"],
             "source_ref": f"{dataset['artifact_id']}@1#/tables/fact_unit_inventory_snapshot/0/unsold_days_dom"},
            {"evidence_id": "ev_price_subject", "metric_ids": ["fact_unit_inventory_snapshot.net_price_per_m2"],
             "source_ref": f"{dataset['artifact_id']}@1#/tables/fact_unit_inventory_snapshot/0/net_price_per_m2"},
        ]},
    )
    insight_evidence = {
        "schema_version": EVIDENCE_SCHEMA,
        "snapshot_id": SNAPSHOT,
        "semantic_config_version": SEMANTIC,
        "dataset_ref": dataset_ref,
        "candidates_ref": {"artifact_id": "mock_candidates_chart_eval", "content_hash": _hash(dataset_payload)},
        "findings": [{
            "finding_id": "mock_finding_dom_high",
            "insight_id": "mock_insight_dom_high",
            "insight_type": "SLOW_MOVING_DRIVER",
            "cause_code": "EXTREME_THERMAL_EXPOSURE",
            "level": "unit",
            "subject": {"type": "unit", "id": subject_key, "label": plan.subject_unit_code},
            "severity_rank": 1,
            "attribution_score": "0.82",
            "confidence": "0.88",
            "metrics": [{
                "metric_id": "fact_unit_inventory_snapshot.unsold_days_dom",
                "slot": "dom",
                "label": "Thời gian trên thị trường (DOM)",
                "value_exact": str(subject_dom),
                "unit": "DAY",
                "role": "primary",
                "source_ref": f"{dataset['artifact_id']}@1#/tables/fact_unit_inventory_snapshot/0/unsold_days_dom",
                "chartable": True,
            }],
            "visual_intents": [
                {"question": "current_value", "chart_type": "kpi_card",
                 "metric_ids": ["fact_unit_inventory_snapshot.unsold_days_dom"]},
                {"question": "target_vs_peer", "chart_type": "bar", "requires": "comparison",
                 "metric_ids": ["fact_unit_inventory_snapshot.unsold_days_dom"]},
            ],
            "limitations": [LIMITATION],
        }],
    }
    insight = _artifact(
        tools,
        artifact_id="mock_insight_chart_eval",
        artifact_type="insight",
        schema_version="insight.v2",
        producer="mock_upstream_llm",
        input_refs=[dataset_ref],
        payload={"summary": {"text": "Mock upstream insight for Chart evaluation."}, "evidence": insight_evidence},
    )
    peer_def = _artifact(
        tools,
        artifact_id="mock_peerdef_chart_eval",
        artifact_type="peer_definition",
        schema_version="peer_definition@1",
        producer="mock_upstream_llm",
        input_refs=[dataset_ref],
        payload={"subject": {"entityType": "unit", "entityId": subject_key, "entityCode": plan.subject_unit_code},
                 "peers": [{"entityId": row["unit_key"], "entityCode": row["unit_code"]} for row in units[1:]],
                 "rule": "same project, same type, similar area; curated for Chart component evaluation"},
    )
    peer_values = [
        {"entityId": subject_key, "entityCode": plan.subject_unit_code, "role": "subject",
         "values": {"dom": subject_dom, "net_asking_price_per_m2": subject_price}},
        *[
            {"entityId": inv["unit_key"], "entityCode": code, "role": "peer",
             "values": {"dom": inv["unsold_days_dom"], "net_asking_price_per_m2": inv["net_price_per_m2"]}}
            for code, inv in zip(peer_codes, peer_rows, strict=True)
        ],
    ]
    chart_hints = [
        {"chartType": "bar", "y": "dom", "purpose": "So sánh DOM mục tiêu với peer"},
        {"chartType": "bar", "y": "net_asking_price_per_m2", "purpose": "So sánh giá ròng/m² mục tiêu với peer"},
        {"chartType": "scatter", "x": "net_asking_price_per_m2", "y": "dom",
         "purpose": "Giá ròng/m² và DOM trong nhóm peer"},
    ]
    if ablation == "no_peer_values":
        peer_values = []
        chart_hints = [hint for hint in chart_hints if hint.get("chartType") != "scatter"]
    comparison = _artifact(
        tools,
        artifact_id="mock_comparison_chart_eval",
        artifact_type="comparison",
        schema_version="comparison@1",
        producer="mock_upstream_llm",
        input_refs=[dataset_ref, _ref(peer_def)],
        payload={
            "subject": {"entityType": "unit", "entityId": subject_key, "entityCode": plan.subject_unit_code},
            "metrics": [
                {"metric": "dom", "unit": "days", "subjectValue": subject_dom,
                 "benchmark": {"stat": "median", "value": peer_dom, "n": len(peer_rows)},
                 "absGap": str(Decimal(str(subject_dom)) - Decimal(str(peer_dom))),
                 "pctGap": _pct_gap(subject_dom, peer_dom),
                 "sourceRef": {"artifactId": dataset["artifact_id"], "table": "fact_unit_inventory_snapshot",
                               "columns": ["unsold_days_dom"]}},
                {"metric": "net_asking_price_per_m2", "unit": "VND/m2", "subjectValue": subject_price,
                 "benchmark": {"stat": "median", "value": peer_price, "n": len(peer_rows)},
                 "absGap": str(Decimal(str(subject_price)) - Decimal(str(peer_price))),
                 "pctGap": _pct_gap(subject_price, peer_price),
                "sourceRef": {"artifactId": dataset["artifact_id"], "table": "fact_unit_inventory_snapshot",
                               "columns": ["net_price_per_m2"]}},
            ],
            "peerValues": peer_values,
            "chartHints": chart_hints,
        },
    )
    refs = [_ref(a) for a in (dataset, metric, dq, evidence, insight, peer_def, comparison)]
    grounding = _validate_grounding(tools, refs)
    step = StepSpec.model_validate({
        "run_id": run_id,
        "plan_id": plan_id,
        "step_id": "B4",
        "idempotency_key": f"{plan_id}:B4",
        "operation": "draw_chart",
        "spec": {"policy_ref": "chart-policy/v1.0"},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": [bundle.project_id], "zone_ids": []}},
        "snapshot_id": SNAPSHOT,
        "semantic_config_version": SEMANTIC,
        "input_refs": refs,
        "original_question": question,
    })
    manifest = {
        "experiment_id": f"chart_eval_{hashlib.sha256(run_id.encode()).hexdigest()[:12]}",
        "question": question,
        "mode": plan.mode,
        "ablation": ablation,
        "planner": plan.planner,
        "planner_metrics": list(plan.metrics),
        "planner_peer_count": plan.peer_count,
        "repair_notes": list(plan.repair_notes),
        "subject_unit_code": plan.subject_unit_code,
        "snapshot": SNAPSHOT,
        "semantic_config_version": SEMANTIC,
        "dataset_ref": f"{dataset['artifact_id']}@{dataset['version']}",
        "source_refs": bundle.source_refs,
        "generated_artifacts": [r["artifact_id"] for r in refs],
        "chart_path": "StepSpec@1 -> run_step",
        "contract_pass": True,
        "grounding_pass": True,
        "grounded_values": grounding["grounded_values"],
        "visual_targets": 3 if ablation == "no_peer_values" else 4,
        "limitations": [LIMITATION],
    }
    return IndependentEvaluation(step=step, tools=tools, manifest=manifest, upstream_refs=refs)


async def run_independent_evaluation(experiment: IndependentEvaluation) -> AgentReport:
    """Run the real Chart StepSpec path against the isolated upstream store."""
    report = await run_step(experiment.step, experiment.tools)
    experiment.manifest["target_success"] = len(report.artifact_refs)
    experiment.manifest["failed_targets"] = 0 if report.state == "completed" else experiment.manifest["visual_targets"]
    experiment.manifest["chart_artifacts"] = [f"{r.artifact_id}@{r.version}" for r in report.artifact_refs]
    return report


async def run_evaluation_suite(question: str, *, subject_unit_code: str | None = None) -> list[EvaluationRun]:
    """Run FULL and ABLATION cases with the same Chart code and policy."""
    runs: list[EvaluationRun] = []
    for name, ablation in (("FULL", "none"), ("ABLATION:no_peer_values", "no_peer_values")):
        experiment = build_independent_evaluation(question, subject_unit_code=subject_unit_code, ablation=ablation)  # type: ignore[arg-type]
        report = await run_independent_evaluation(experiment)
        runs.append(EvaluationRun(name=name, experiment=experiment, report=report))
    return runs


def persist_experiment_report(runs: list[EvaluationRun], *, suite_name: str = "MOCK") -> EvaluationSuite:
    if not runs:
        raise ValueError("cannot persist an empty evaluation suite")
    owner = runs[0].experiment
    payload = {
        "schema_version": "chart_eval_report@1",
        "suite": suite_name,
        "overall": {
            "state": "PASS" if all(run.report.state == "completed" for run in runs) else "FAIL",
            "runs": len(runs),
            "total_chart_specs": sum(len(run.report.artifact_refs) for run in runs),
            "limitation": LIMITATION,
        },
        "runs": [
            {
                "name": run.name,
                "state": run.report.state,
                "summary": run.report.summary,
                "manifest": run.experiment.manifest,
            }
            for run in runs
        ],
    }
    report_env = _artifact(
        owner.tools,
        artifact_id=f"mock_chart_eval_report_{suite_name.lower()}",
        artifact_type="report",
        schema_version="chart_eval_report@1",
        producer="chart_eval_harness",
        input_refs=owner.upstream_refs,
        source_refs=owner.manifest.get("source_refs", []),
        payload=payload,
    )
    report_ref = f"{report_env['artifact_id']}@{report_env['version']}"
    for run in runs:
        run.experiment.manifest["suite_report_ref"] = report_ref
    payload["report_ref"] = report_ref
    return EvaluationSuite(name=suite_name, runs=runs, report_ref=report_ref, report=payload)


async def run_persisted_evaluation_suite(question: str, *, subject_unit_code: str | None = None) -> EvaluationSuite:
    runs = await run_evaluation_suite(question, subject_unit_code=subject_unit_code)
    return persist_experiment_report(runs, suite_name="MOCK")


async def run_golden_evaluation_suite(question: str = "Vì sao căn MAS-U00283 bán chậm? So sánh và vẽ biểu đồ.") -> EvaluationSuite:
    plan = UpstreamSimulationPlan(
        question=question,
        subject_unit_code="MAS-U00283",
        mode="golden",
        metrics=ALLOWED_PLAN_METRICS,
        peer_count=4,
        planner="golden",
    )
    runs: list[EvaluationRun] = []
    for name, ablation in (("GOLDEN:FULL", "none"), ("GOLDEN:ABLATION:no_peer_values", "no_peer_values")):
        experiment = build_independent_evaluation(question, ablation=ablation, simulation_plan=plan)  # type: ignore[arg-type]
        report = await run_independent_evaluation(experiment)
        runs.append(EvaluationRun(name=name, experiment=experiment, report=report))
    return persist_experiment_report(runs, suite_name="GOLDEN")


def live_runner_report(question: str) -> dict[str, Any]:
    return {
        "schema_version": "chart_eval_live_runner@1",
        "question": question,
        "state": "not_run",
        "reason": "LIVE runner is wired as a boundary report; it requires real pinned upstream artifacts from Data/Insight/Compare.",
        "expected_input": "StepSpec@1 draw_chart with dataset/insight/comparison/peer_definition refs from a live Orchestrator run",
    }
