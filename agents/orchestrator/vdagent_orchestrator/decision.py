"""Tier 3 — the decision question (build spec 01 §10.3), turn based (DEC-025: no expiry timer).

Every part flagged `awaiting_decision` goes into one card, shown only when no other question or replan is waiting and
nothing can run. "Dùng kết quả hiện có" reports every flagged part directly; "Thử lại phần …" creates a new step with
the same agent, operation and spec (new id and idempotency key, no LLM call, uses the retry reserve), rewires its
waiters, and reports the other flagged parts directly. A run asks this question once.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from vdagent_orchestrator.dispatcher import AWAITING, maybe_close, ready, report_direct, rewire
from vdagent_orchestrator.inputs import Choice
from vdagent_orchestrator.records import RunRecord, StepRecord, record_for
from vdagent_orchestrator.simple_router import normalize
from vdagent_orchestrator.wording import card_title, part, retry_label

USE_CURRENT = "Dùng kết quả hiện có"
USE_CURRENT_ID = "USE_CURRENT"


class DecisionCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["DECISION"] = "DECISION"
    input_id: str
    title: str
    lines: list[str]
    choices: list[Choice]

    def render(self) -> str:
        return "\n".join([self.title, *self.lines, *(f"{i}. {c.label}" for i, c in enumerate(self.choices, start=1))])


def _flagged(run: RunRecord) -> list[StepRecord]:
    return [run.steps[p["step_id"]] for p in run.pending if p["kind"] == "DECISION"]


def _mention(run: RunRecord) -> str:
    return run.frame.mentions[0].text if run.frame.mentions else "câu hỏi này"


def _card(run: RunRecord, flagged: list[StepRecord]) -> DecisionCard:
    done = [part(s.agent) for s in run.ordered() if s.status == "completed"]
    lines = [f"Đã có: {', '.join(dict.fromkeys(done)) or 'chưa có phần nào'}.",
             *(f"Lý do: {s.error_message or 'kết quả chưa đạt kiểm tra'}" for s in flagged),
             "Nếu dùng kết quả hiện có: các phần còn lại vẫn hiển thị, thiếu phần trên."]
    choices = [Choice(id=USE_CURRENT_ID, label=USE_CURRENT),
               *(Choice(id=f"RETRY:{s.step_id}", label=retry_label(s.agent)) for s in flagged)]
    return DecisionCard(input_id=f"decision-{run.run_id}", title=card_title(flagged[0].agent, _mention(run)),
                        lines=lines, choices=choices)


def open_decision(run: RunRecord) -> DecisionCard | None:
    flagged = _flagged(run)
    if not flagged or run.finished:
        return None
    if any(p["kind"] in ("INPUT", "REPLAN") for p in run.pending) or ready(run):
        return None  # batch: ask when nothing else can move
    if any(s.status in ("working", "input_required") for s in run.steps.values()):
        return None
    if not run.decision_asked:
        run.decision_asked = True
        run.event("INPUT_REQUESTED", kind="DECISION", steps=[s.step_id for s in flagged])
    run.status = "input_required"
    return _card(run, flagged)


def _use_current(run: RunRecord, step: StepRecord) -> None:
    step.flags = [f for f in step.flags if f not in AWAITING]
    report_direct(run, step)


def _retry(run: RunRecord, old: StepRecord) -> StepRecord:
    planned = run.plan.step(old.step_id)
    new_id = f"B{run.plan.next_step_no}"
    copy = planned.model_copy(update={"step_id": new_id, "idempotency_key": f"{run.plan.plan_id}:{new_id}",
                                      "replaces": old.step_id, "forward_to": []})
    run.plan = run.plan.model_copy(update={"steps": [*run.plan.steps, copy], "next_step_no": run.plan.next_step_no + 1})
    record = record_for(copy)
    record.part_id, record.replan_used = old.part_id, True
    run.steps[new_id] = record
    old.flags = [f for f in old.flags if f not in AWAITING]
    run.retry_reserve_used += 1
    rewire(run, old.step_id, new_id)
    run.event("STEP_RETRY", step_id=new_id, replaces=old.step_id)
    return record


def answer_decision(run: RunRecord, text: str) -> Literal["USE_CURRENT", "RETRY", "NO_MATCH", "NOT_AWAITING"]:
    flagged = _flagged(run)
    if not flagged or not run.decision_asked or run.finished:
        return "NOT_AWAITING"
    card = _card(run, flagged)
    said = normalize(text)
    choice = next((c for i, c in enumerate(card.choices, start=1)
                   if said in (str(i), normalize(c.id), normalize(c.label))), None)
    if choice is None:
        return "NO_MATCH"
    run.pending = [p for p in run.pending if p["kind"] != "DECISION"]
    run.status = "working"
    run.sales_ops_inputs.append({"kind": "DECISION", "choice": choice.label, "expired": False})
    run.event("INPUT_ANSWERED", kind="DECISION", choice=choice.id)
    retried = choice.id.removeprefix("RETRY:") if choice.id.startswith("RETRY:") else None
    for step in flagged:
        if step.step_id == retried:
            _retry(run, step)
        else:
            _use_current(run, step)
    maybe_close(run)
    return "RETRY" if retried else "USE_CURRENT"


__all__ = ["USE_CURRENT", "DecisionCard", "answer_decision", "open_decision"]
