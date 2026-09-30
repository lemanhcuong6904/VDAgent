"""Deterministic planning for the approved real-estate workflow (WS5).

`classify` recognises a question about one unit (a unit code such as `A12-08`) and what is asked:
explain (vì sao / tại sao / nguyên nhân / bán chậm), compare (so sánh / tương đồng / peer), chart (biểu đồ /
đồ thị / chart). No unit code → None: the question is not forced into the DAG (legacy LLM loop, or an explanation).
A chart without an analysis asks for both analyses (Chart only draws Insight/Compare outputs).
`parse_request` reads the structured `AnalysisRequest@1` contract. Neither ever picks a snapshot: the snapshot and
semantic version come from the request or from the Orchestrator's explicit configuration.

`build_plan` turns a request into B1 Data → B2 Insight / B3 Compare (same B1 refs) → B4 Chart (any of B2/B3).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .dag import InputBinding, Plan, PlanError, PlanStep

UNIT_CODE = re.compile(r"\b([A-Z]{1,3}\d{1,3}-\d{1,3}(?:\.\d{1,3})?)\b")
WANTS = ("explain", "compare", "chart", "report")
_KEYWORDS = {
    "explain": ("vi sao", "tai sao", "nguyen nhan", "ban cham", "ly do"),
    "compare": ("so sanh", "tuong dong", "peer"),
    "chart": ("bieu do", "chart", "do thi"),  # not "ve": "về" folds to it too
    "report": ("bao cao", "xuat bao cao", "report"),
}
DATA_TYPES = ("dataset", "metric", "dq")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn") + " "


@dataclass(frozen=True)
class AnalysisRequest:
    question: str
    subject_unit_code: str
    wants: frozenset[str]
    snapshot_id: str | None
    semantic_config_version: str | None


def normalize_wants(wants: set[str] | frozenset[str]) -> frozenset[str]:
    """What a request really needs (shared by the deterministic and the LLM planner):
    charts or a report without a named analysis need both analyses (Chart only draws Insight and Compare outputs:
    KPI cards from Insight, target-vs-peer and scatter charts from Compare); a report embeds the charts."""
    wants = set(wants)
    if wants & {"chart", "report"} and not wants & {"explain", "compare"}:
        wants |= {"explain", "compare"}
    if "report" in wants:
        wants.add("chart")
    return frozenset(wants)


def classify(question: str, *, snapshot_id: str | None, semantic_config_version: str | None) -> AnalysisRequest | None:
    codes = UNIT_CODE.findall(question)
    if len(set(codes)) != 1:
        return None  # none, or ambiguous between several units: no guess
    folded = _fold(question)
    wants = {w for w, words in _KEYWORDS.items() if any(k in folded for k in words)}
    if not wants:
        return None
    return AnalysisRequest(question, codes[0], normalize_wants(wants), snapshot_id, semantic_config_version)


def parse_request(data: Mapping[str, Any]) -> AnalysisRequest:
    if data.get("contract") != "AnalysisRequest@1":
        raise PlanError("INVALID_REQUEST", "expected contract AnalysisRequest@1")
    question, code = data.get("question"), data.get("subject_unit_code")
    wants = data.get("wants")
    if not isinstance(question, str) or not isinstance(code, str) or not UNIT_CODE.fullmatch(code):
        raise PlanError("INVALID_REQUEST", "question and a subject_unit_code (e.g. A12-08) are required")
    if not isinstance(wants, list) or not wants or not set(wants) <= set(WANTS):
        raise PlanError("INVALID_REQUEST", f"wants must be a non-empty subset of {list(WANTS)}")
    snapshot, semantic = data.get("snapshot_id"), data.get("semantic_config_version")
    if not isinstance(snapshot, str) or not snapshot or not isinstance(semantic, str) or not semantic:
        raise PlanError("INVALID_REQUEST", "snapshot_id and semantic_config_version are required (no default snapshot)")
    return AnalysisRequest(question, code, frozenset(wants), snapshot, semantic)


# What each step consumes from the step it depends on (the executor forwards only these artifact types).
STEP_OUTPUTS = {"data": DATA_TYPES, "insight": ("insight",), "compare": ("peer_definition", "comparison"),
                "chart": ("chart_spec",), "report": ("report",)}


def step_spec(agent: str, unit_code: str, population: str, data_step: str = "B1") -> dict[str, Any]:
    """The code-owned StepSpec `spec` of each operation (never written by an LLM)."""
    if agent == "data":
        return {"subject_unit_code": unit_code, "population": population}
    if agent == "insight":
        return {"intent": "SLOW_MOVING_INVESTIGATION", "tasks": ["T1", "T7"], "analysis_scope": {"$subject_scope_of": data_step}}
    if agent == "compare":
        return {"subject": {"entityType": "unit", "entityCode": unit_code}, "comparisonMode": "peer_group"}
    return {}  # chart, report: everything comes from their inputs


def build_plan(request: AnalysisRequest, run_id: str) -> Plan:
    if not request.snapshot_id:
        raise PlanError("SNAPSHOT_REQUIRED", "no snapshot configured or requested")
    if not request.semantic_config_version:
        raise PlanError("SEMANTIC_VERSION_REQUIRED", "no semantic config version configured or requested")
    wants = set(normalize_wants(request.wants))
    population = "peer_candidates" if "compare" in wants else "subject"
    steps = [PlanStep("B1", "data", "fetch_units", step_spec("data", request.subject_unit_code, population))]
    analyses: list[tuple[str, tuple[str, ...]]] = []
    n = 2
    if "explain" in wants:
        steps.append(PlanStep(f"B{n}", "insight", "explain_unit", step_spec("insight", request.subject_unit_code, population, "B1"),
                              ("B1",), "all", (InputBinding("B1", DATA_TYPES),)))
        analyses.append((f"B{n}", ("insight",)))
        n += 1
    if "compare" in wants:
        steps.append(PlanStep(f"B{n}", "compare", "compare_to_peers", step_spec("compare", request.subject_unit_code, population),
                              ("B1",), "all", (InputBinding("B1", DATA_TYPES),)))
        analyses.append((f"B{n}", ("peer_definition", "comparison")))
        n += 1
    chart_step = None
    if "chart" in wants:
        chart_step = f"B{n}"
        steps.append(PlanStep(chart_step, "chart", "draw_chart", {}, tuple(s for s, _ in analyses), "any",
                              tuple(InputBinding(s, types) for s, types in analyses)))
        n += 1
    if "report" in wants:
        sources = list(analyses)
        if chart_step is not None:
            sources.append((chart_step, ("chart_spec",)))
        steps.append(PlanStep(f"B{n}", "report", "draft_report", {}, tuple(s for s, _ in sources), "any",
                              tuple(InputBinding(s, types) for s, types in sources)))
    identity = json.dumps({"run": run_id, "code": request.subject_unit_code, "wants": sorted(wants),
                           "snapshot": request.snapshot_id, "semantic": request.semantic_config_version}, sort_keys=True)
    plan_id = "pl_" + hashlib.sha256(identity.encode()).hexdigest()[:12]
    return Plan(plan_id, run_id, request.snapshot_id, request.semantic_config_version, request.question, tuple(steps))
