"""Agent questions (build spec 01 §10.4), turn based (DEC-025): the turn ends with a card; the next message answers it.

An answer is recorded in `IntentFrame.answered_choices` (DEC-027) and the step is sent again under the same
idempotency key. "Không phải các lựa chọn này" cancels the step and reports it directly; a run asks Sales Ops at most
twice — the 3rd question cancels its step.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import AnsweredChoice
from vdagent_orchestrator.dispatcher import maybe_close, report_direct
from vdagent_orchestrator.records import RunRecord, StepRecord
from vdagent_orchestrator.simple_router import normalize

NONE_OF_THESE = "Không phải các lựa chọn này"
NONE_ID = "NONE"
MAX_AGENT_QUESTIONS = 2
DECLINED_HINT = "Bạn chưa chọn được đối tượng; hãy hỏi lại với tên rõ hơn (ví dụ tên phân khu hoặc mã căn đầy đủ)."
TOO_MANY_HINT = "Hệ thống đã hỏi lại quá số lần cho phép; hãy hỏi lại với tên rõ hơn."


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    label: str


class InputCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["AGENT_QUESTION"] = "AGENT_QUESTION"
    input_id: str
    step_id: str
    text: str
    choices: list[Choice]

    def render(self) -> str:
        lines = [self.text, *(f"{i}. {c.label}" for i, c in enumerate(self.choices, start=1))]
        return "\n".join(lines)


def _card(step: StepRecord) -> InputCard:
    assert step.question is not None
    options = [Choice(id=o.id, label=o.label) for o in step.question.options]
    return InputCard(input_id=step.question.input_id or f"{step.step_id}:0", step_id=step.step_id, text=step.question.text,
                     choices=[*options, Choice(id=NONE_ID, label=NONE_OF_THESE)])


def _cancel(run: RunRecord, step: StepRecord, code: str, message: str) -> None:
    step.status, step.error_code, step.error_class, step.error_message = "canceled", code, ErrorClass.NEED_INPUT, message
    step.question = None
    run.event("STEP_CANCELED", step_id=step.step_id, code=code)
    report_direct(run, step)
    maybe_close(run)


def open_question(run: RunRecord) -> InputCard | None:
    """The card to show now (at most one); counts each agent question once; the 3rd question cancels its step."""
    for item in [p for p in run.pending if p["kind"] == "INPUT"]:
        step = run.steps[item["step_id"]]
        if not item.get("asked"):
            if run.agent_questions >= MAX_AGENT_QUESTIONS:
                run.pending.remove(item)
                _cancel(run, step, "TOO_MANY_QUESTIONS", TOO_MANY_HINT)
                continue
            run.agent_questions += 1
            item["asked"] = True
        run.status = "input_required"
        return _card(step)
    if run.status == "input_required":
        run.status = "working"
    return None


def _match(card: InputCard, text: str) -> Choice | None:
    said = normalize(text)
    if said.isdigit() and 1 <= int(said) <= len(card.choices):
        return card.choices[int(said) - 1]
    for choice in card.choices:
        if said in (normalize(choice.id), normalize(choice.label)):
            return choice
    return None


def answer(run: RunRecord, text: str) -> Literal["RESUMED", "CANCELED", "NO_MATCH", "NOT_AWAITING"]:
    item = next((p for p in run.pending if p["kind"] == "INPUT" and p.get("asked")), None)
    if item is None or run.finished:
        return "NOT_AWAITING"
    step = run.steps[item["step_id"]]
    card = _card(step)
    choice = _match(card, text)
    if choice is None:
        return "NO_MATCH"
    run.pending.remove(item)
    run.status = "working"
    run.event("INPUT_ANSWERED", step_id=step.step_id, input_id=card.input_id, choice=choice.id)
    run.sales_ops_inputs.append({"kind": "AGENT_QUESTION", "choice": choice.label, "expired": False})
    if choice.id == NONE_ID:
        _cancel(run, step, "INPUT_DECLINED", DECLINED_HINT)
        return "CANCELED"
    kept = [a for a in run.frame.answered_choices if a.input_id != card.input_id]
    run.frame = run.frame.model_copy(update={"answered_choices": [*kept, AnsweredChoice(input_id=card.input_id,
                                                                                         choice=choice.id)]})
    step.question, step.resend = None, True
    step.status = "working"
    return "RESUMED"


__all__ = ["MAX_AGENT_QUESTIONS", "NONE_OF_THESE", "Choice", "InputCard", "answer", "open_question"]
