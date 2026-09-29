"""Understanding the question (build spec 01 §4): IntentDraft from LLM 1, the clarify rules A1–A6, default outputs.

Pure code except the LLM call in llm1.py. Mentions are passed as typed (INT-9): Data resolves them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vdagent_contracts.intents import OutputKind, TaskKind

ScopeCheck = Literal["ANALYSIS", "DECISION_REQUEST", "OFF_TOPIC"]
MAX_CLARIFY_ROUNDS = 2

WHAT_WE_ANSWER = ("Tôi trả lời câu hỏi phân tích về tồn kho, giá, tốc độ bán và nguyên nhân bán chậm của các dự án"
                  " bạn được xem.")
ASK_OBJECT = "Bạn muốn xem dự án, phân khu hay căn nào?"
DEFAULT_OUTPUTS_EXPLAIN = "Bạn chưa nói cần gì; hệ thống trả lời trong chat, kèm biểu đồ và báo cáo nháp."
DEFAULT_OUTPUTS_CHAT = "Bạn chưa nói cần gì; hệ thống trả lời trong chat."


class Mention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str
    kind_hint: Literal["PROJECT", "ZONE", "UNIT", "UNKNOWN"] = "UNKNOWN"


class IntentDraft(BaseModel):
    """What LLM 1 returns (names are checked against the Data vocabulary by the caller, INT-3)."""

    model_config = ConfigDict(extra="forbid")
    scope_check: ScopeCheck
    task_kinds: list[TaskKind] = Field(default_factory=list)
    mentions: list[Mention] = Field(default_factory=list)
    scope_all: bool = False
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    phenomena: list[str] = Field(default_factory=list)
    unmatched_needs: list[str] = Field(default_factory=list)
    requested_outputs: list[OutputKind] = Field(default_factory=list)
    decision_part: str | None = None
    is_follow_up: bool = False


class AnsweredChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_id: str
    choice: str


class IntentFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_check: ScopeCheck
    task_kinds: list[TaskKind]
    mentions: list[Mention]
    scope_all: bool
    metrics: list[str]
    dimensions: list[str]
    filters: list[str]
    phenomena: list[str]
    unmatched_needs: list[str]
    requested_outputs: list[OutputKind]
    uncovered_task_kinds: list[TaskKind] = Field(default_factory=list)
    original_question: str
    parent_run_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    source: Literal["UI_SELECTION", "LLM", "SIMPLE_ROUTER"] = "LLM"
    plan_source: Literal["LLM", "FALLBACK"] | None = None
    answered_choices: list[AnsweredChoice] = Field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    decision: Literal["PROCEED", "ASK", "REJECT"]
    frame: IntentFrame | None = None
    questions: list[str] = field(default_factory=list)
    reason: str | None = None


def default_outputs(draft: IntentDraft) -> tuple[list[OutputKind], str | None]:
    """INT-7: explicit outputs win; else EXPLAIN → chat + chart + report, otherwise chat only (with an assumption)."""
    if draft.requested_outputs:
        return list(draft.requested_outputs), None
    if TaskKind.EXPLAIN in draft.task_kinds:
        return [OutputKind.CHAT_ANSWER, OutputKind.CHART, OutputKind.REPORT], DEFAULT_OUTPUTS_EXPLAIN
    return [OutputKind.CHAT_ANSWER], DEFAULT_OUTPUTS_CHAT


def decide(draft: IntentDraft, *, question: str, served: set[TaskKind], clarify_rounds: int = 0,
           ui_scope: bool = False, metric_suggestions: Sequence[str] = ()) -> Decision:
    """INT-5, evaluated in order A1 … A6."""
    if draft.scope_check == "OFF_TOPIC":  # A1
        return Decision("REJECT", reason=f"Câu hỏi nằm ngoài lĩnh vực hệ thống hỗ trợ. {WHAT_WE_ANSWER}")
    if draft.scope_check == "DECISION_REQUEST":  # A2
        return Decision("REJECT", reason=("Hệ thống không đưa ra quyết định thay bạn. Bạn có thể hỏi phân tích, ví dụ:"
                                          " \"Vì sao căn này bán chậm?\" hoặc \"Giá căn này so với nhóm tương đồng thế nào?\""))
    assumptions: list[str] = []
    if draft.decision_part:
        assumptions.append(f"Phần yêu cầu quyết định (\"{draft.decision_part}\") không được thực hiện; chỉ làm phần phân tích.")
    uncovered = [k for k in draft.task_kinds if k not in served]
    if draft.task_kinds and len(uncovered) == len(draft.task_kinds):  # A3
        names = ", ".join(k.value for k in uncovered)
        return Decision("REJECT", reason=f"Hệ thống chưa có chức năng cho loại câu hỏi này ({names}). {WHAT_WE_ANSWER}")
    if uncovered:
        assumptions.append(f"Chưa làm được phần: {', '.join(k.value for k in uncovered)}.")
    has_object = bool(draft.mentions) or ui_scope or draft.scope_all
    has_need = bool(draft.metrics or draft.phenomena or draft.task_kinds)
    if (not has_object or not has_need) and clarify_rounds >= MAX_CLARIFY_ROUNDS:  # A6
        return Decision("REJECT", reason="Chưa xác định được bạn muốn xem gì. Hãy chọn phạm vi ở bộ lọc rồi hỏi lại.")
    questions: list[str] = []
    if not has_object:  # A4
        questions.append(ASK_OBJECT)
    if not has_need:  # A5
        target = draft.mentions[0].text if draft.mentions else "đối tượng này"
        hints = ", ".join(list(metric_suggestions)[:3]) or "tốc độ bán, giá, tồn kho"
        questions.append(f"Bạn muốn xem gì về {target}: {hints}…?")
    if questions:
        return Decision("ASK", questions=questions[:3])
    outputs, output_assumption = default_outputs(draft)
    if output_assumption:
        assumptions.append(output_assumption)
    frame = IntentFrame(
        scope_check=draft.scope_check, task_kinds=[k for k in draft.task_kinds if k in served], mentions=draft.mentions,
        scope_all=draft.scope_all, metrics=draft.metrics, dimensions=draft.dimensions, filters=draft.filters,
        phenomena=draft.phenomena, unmatched_needs=draft.unmatched_needs, requested_outputs=outputs,
        uncovered_task_kinds=uncovered, original_question=question, assumptions=assumptions,
    )
    return Decision("PROCEED", frame=frame)
