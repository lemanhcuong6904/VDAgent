"""S1 understand & resolve (build spec 02 §5, DEC-027): mentions → entity ids, or a closed-choice question.

Earlier answers of this run arrive in `StepSpec.answered_choices` (keyed by the question's `input_id`), so a later
Data step never asks Sales Ops twice. A spec that contradicts the original question is `SPEC_MISMATCH`; Data never
corrects the spec itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vdagent_agentkit.mcp_client import McpSession
from vdagent_contracts.messages import StepSpec
from vdagent_data.pipeline.s0_intake import Failure
from vdagent_data.semantic.loader import normalize
from vdagent_data.specs import CommonSpec
from vdagent_data.value_index import Ambiguous, Match, NotFound, Option, ValueIndex, load_index

SCOPE_KEY = {"PROJECT": "project_key", "ZONE": "zone_key", "UNIT": "unit_key"}
KIND_VI = {"PROJECT": "dự án", "ZONE": "phân khu", "UNIT": "căn"}

# (words in the question, filters that contradict them)
CONTRADICTIONS: list[tuple[tuple[str, ...], frozenset[str]]] = [
    (("ban cham", "ton lau", "qua han", "kho ban", "chua ban"), frozenset({"sold"})),
    (("da ban",), frozenset({"slow_moving", "available"})),
]


@dataclass(frozen=True)
class Question:
    code: str  # AMBIGUOUS_REQUEST | ENTITY_NOT_FOUND
    input_id: str
    text: str
    options: list[Option]


@dataclass(frozen=True)
class Resolution:
    resolved: dict[str, dict[str, Any]] = field(default_factory=dict)
    scope_filters: dict[str, list[str]] = field(default_factory=dict)
    index: ValueIndex | None = None


def _contradiction(question: str, filters: list[str]) -> str | None:
    text = normalize(question)
    for words, bad in CONTRADICTIONS:
        hit = next((w for w in words if w in text), None)
        clash = bad & set(filters)
        if hit and clash:
            return f"Câu hỏi nói \"{hit}\" nhưng bước dữ liệu lọc {', '.join(sorted(clash))}."
    return None


async def resolve_step(step: StepSpec, spec: CommonSpec, session: McpSession) -> Resolution | Question | Failure:
    clash = _contradiction(step.original_question, spec.filters)
    if clash:
        return Failure("SPEC_MISMATCH", clash)
    question_text = normalize(step.original_question)
    for mention in spec.scope.mentions:
        if normalize(mention.text) not in question_text:
            return Failure("SPEC_MISMATCH", f"Đối tượng \"{mention.text}\" không có trong câu hỏi gốc.")

    index = await load_index(session)
    answers = {a.input_id: a.choice for a in step.answered_choices}
    resolved: dict[str, dict[str, Any]] = {}
    filters: dict[str, list[str]] = {}
    for i, mention in enumerate(spec.scope.mentions):
        input_id = f"{step.step_id}:{i}"
        # an answer to this mention's question, asked by this step or an earlier Data step of the run
        chosen = answers.get(input_id) or next(
            (c for key, c in answers.items() if key.endswith(f":{i}") and index.get(c) is not None), None
        )
        entry = index.get(chosen) if chosen else None
        if entry is not None:
            result: Match | Ambiguous | NotFound = Match(kind=entry.kind, ids=[entry.id], label=entry.label)
        else:
            result = index.resolve(mention.text, mention.kind_hint)
        if isinstance(result, Ambiguous):
            return Question(
                code="AMBIGUOUS_REQUEST",
                input_id=input_id,
                text=f"\"{mention.text}\" khớp với nhiều {KIND_VI[result.kind]}. Bạn muốn xem {KIND_VI[result.kind]} nào?",
                options=result.options,
            )
        if isinstance(result, NotFound):
            if result.suggestions:
                return Question(
                    code="ENTITY_NOT_FOUND",
                    input_id=input_id,
                    text=f"Không tìm thấy \"{mention.text}\". Có phải bạn muốn nói tới một trong các lựa chọn sau?",
                    options=result.suggestions,
                )
            return Failure("ENTITY_NOT_FOUND", f"Không tìm thấy \"{mention.text}\" trong phạm vi dữ liệu bạn được xem.")
        resolved[mention.text] = {"kind": result.kind, "ids": result.ids, "label": result.label}
        filters.setdefault(SCOPE_KEY[result.kind], []).extend(result.ids)
    return Resolution(resolved=resolved, scope_filters={k: sorted(set(v)) for k, v in filters.items()}, index=index)
