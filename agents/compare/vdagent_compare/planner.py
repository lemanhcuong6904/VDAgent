"""Question → comparison request (spec §1.9, `ComparisonPlan`).

The model fills `PLAN_SCHEMA`; `plan_to_request` then checks it the way the engine's input
contract does. A plan that names an entity absent from the conversation is refused: the model
may pick the comparison, never invent the unit it compares.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .llm import JsonLLM
from .vh_chat import PEER_TABLE_METRICS
from .vh_math import DIRECTIONS

PROMPT = (Path(__file__).parent / "prompts" / "plan.md").read_text(encoding="utf-8").strip()
MODES = ("peer_group", "head_to_head", "cohort", "ranking", "external_benchmark")
METRICS = tuple(DIRECTIONS)
DIMENSIONS = ("floor_band", "balcony_orientation", "orientation_group", "view_type", "area_band", "zone_id")
MUST_MATCH = ("balcony_orientation", "view_type", "zone_id")
UNIT_TYPES = ("STUDIO", "1PN", "2PN", "3PN", "4PN")


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_ENTITY = {
    "type": "object", "additionalProperties": False, "required": ["entityType", "entityCode"],
    "properties": {"entityType": {"type": "string", "enum": ["unit", "zone", "project"]},
                   "entityCode": {"type": "string"}},
}
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["intent", "comparisonMode", "subject", "targets", "metricsRequested", "cohortDimension",
                 "unitTypeFilter", "criteriaOverride", "rankingOptions", "clarificationQuestion"],
    "properties": {
        "intent": {"type": "string", "enum": ["compare", "clarify", "out_of_scope"]},
        "comparisonMode": _nullable({"type": "string", "enum": list(MODES)}),
        "subject": _nullable(_ENTITY),
        "targets": {"type": "array", "items": _ENTITY},
        "metricsRequested": _nullable({"type": "array", "items": {"type": "string", "enum": list(METRICS)}}),
        "cohortDimension": _nullable({"type": "string", "enum": list(DIMENSIONS)}),
        "unitTypeFilter": _nullable({"type": "string", "enum": list(UNIT_TYPES)}),
        "criteriaOverride": _nullable({
            "type": "object", "additionalProperties": False, "required": ["mustMatch", "areaBandPct"],
            "properties": {"mustMatch": {"type": "array", "items": {"type": "string", "enum": list(MUST_MATCH)}},
                           "areaBandPct": _nullable({"type": "number"})},
        }),
        "rankingOptions": _nullable({
            "type": "object", "additionalProperties": False, "required": ["topN", "order"],
            "properties": {"topN": _nullable({"type": "integer"}),
                           "order": _nullable({"type": "string", "enum": ["attention_first", "best_first"]})},
        }),
        "clarificationQuestion": _nullable({"type": "string"}),
    },
}


@dataclass(frozen=True)
class Plan:
    kind: str  # "request" | "clarify" | "out_of_scope" | "rejected"
    request: dict | None = None
    message: str = ""


def _mentioned(code: str, text: str) -> bool:
    squash = lambda s: re.sub(r"\s+", "", s.upper())  # noqa: E731
    return squash(code) in squash(text)


def plan_to_request(plan: dict, conversation: str) -> Plan:
    """Check a model plan against the engine's input rules; `rejected` carries the reason."""
    intent = plan.get("intent")
    if intent == "out_of_scope":
        return Plan("out_of_scope")
    if intent == "clarify":
        question = (plan.get("clarificationQuestion") or "").strip()
        return Plan("clarify", message=question) if question else Plan("rejected", message="clarify without question")
    if intent != "compare":
        return Plan("rejected", message=f"unknown intent {intent!r}")
    subject = plan.get("subject")
    if not isinstance(subject, dict) or not subject.get("entityCode"):
        return Plan("rejected", message="compare without subject")
    entities = [subject, *(plan.get("targets") or [])]
    invented = [e["entityCode"] for e in entities if not _mentioned(str(e.get("entityCode", "")), conversation)]
    if invented:
        return Plan("rejected", message=f"entity not in the conversation: {', '.join(invented)}")
    request: dict[str, Any] = {
        "subject": {"entityType": subject["entityType"], "entityCode": subject["entityCode"].strip().upper()},
        "comparisonMode": plan.get("comparisonMode") or ("peer_group" if subject["entityType"] == "unit" else "ranking"),
    }
    if plan.get("targets"):
        request["targets"] = [{"entityType": t["entityType"], "entityCode": t["entityCode"].strip().upper()}
                              for t in plan["targets"]]
    for key in ("metricsRequested", "cohortDimension", "unitTypeFilter"):
        if plan.get(key):
            request[key] = plan[key]
    override = plan.get("criteriaOverride") or {}
    cleaned = {k: v for k, v in {"mustMatch": override.get("mustMatch") or None,
                                 "areaBandPct": override.get("areaBandPct")}.items() if v is not None}
    if cleaned:
        request["criteriaOverride"] = cleaned
    ranking = plan.get("rankingOptions") or {}
    options = {k: v for k, v in {"topN": ranking.get("topN"), "order": ranking.get("order")}.items() if v is not None}
    if options:
        request["rankingOptions"] = options
    if request["comparisonMode"] == "ranking" and not request.get("metricsRequested"):
        request["metricsRequested"] = ["dom"]
    if request["comparisonMode"] == "peer_group" and not request.get("metricsRequested"):
        request["metricsRequested"] = list(PEER_TABLE_METRICS)  # the Compare screen's default columns (§3.5)
    return Plan("request", request=request)


def plan_messages(question: str, earlier: list[str]) -> list[dict[str, str]]:
    context = "\n".join(f"- {line}" for line in earlier[-6:]) or "(không có)"
    return [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"Các lượt trước (chỉ để hiểu câu hỏi tiếp nối):\n{context}\n\n"
                                    f"Câu hỏi hiện tại:\n{question}"},
    ]


async def plan(llm: JsonLLM, question: str, earlier: list[str]) -> Plan:
    """Ask the model for a plan; `LLMUnavailableError` propagates so the caller can fall back."""
    reply = await llm.complete_json(plan_messages(question, earlier), name="comparison_plan", schema=PLAN_SCHEMA)
    return plan_to_request(reply, "\n".join([*earlier, question]))
