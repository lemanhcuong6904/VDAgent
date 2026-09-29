"""Conversation state between turns (R1, DEC-025): the current run and what the Orchestrator is waiting for, kept as
one `run_state` note in `ctx.memory`. A message when nothing is awaited is a new question (H9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vdagent_orchestrator.records import RunRecord
from vdagent_sdk import Memory

STATE_KIND = "run_state"
Route = Literal["NEW_QUESTION", "CLARIFY_ANSWER", "ANSWER", "DECISION_ANSWER", "CONTINUE"]


class Awaiting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["CLARIFY", "AGENT_QUESTION", "DECISION"]
    input_id: str | None = None
    question: str | None = None  # CLARIFY: the original question
    questions: list[str] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)  # CLARIFY answers so far
    rounds: int = 0

    def resume_clarify(self, text: str) -> tuple[str, list[str], int]:
        """INT-6: re-understand the original question with every answer given so far."""
        assert self.kind == "CLARIFY" and self.question is not None
        return self.question, [*self.answers, text], self.rounds


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run: RunRecord | None = None
    awaiting: Awaiting | None = None
    llm_calls: int = 0  # every provider call for the current question, clarification included (cap 9)


def route_message(state: ConversationState, text: str) -> Route:
    awaiting = state.awaiting
    if awaiting is None:
        # a run stopped by the turn's step budget (R7) goes on with any message
        return "CONTINUE" if state.run is not None and not state.run.finished else "NEW_QUESTION"
    if awaiting.kind == "CLARIFY":
        return "CLARIFY_ANSWER"
    if state.run is None or state.run.finished:
        return "NEW_QUESTION"
    return "ANSWER" if awaiting.kind == "AGENT_QUESTION" else "DECISION_ANSWER"


async def save_state(memory: Memory, state: ConversationState) -> None:
    old = [n for n in await memory.recent(50) if n.kind == STATE_KIND]
    await memory.save(state.model_dump_json(), kind=STATE_KIND)
    for note in old:
        await memory.delete(note.id)


async def load_state(memory: Memory) -> ConversationState:
    for note in await memory.recent(50):
        if note.kind == STATE_KIND:
            try:
                return ConversationState.model_validate_json(note.text)
            except ValidationError:  # written by an older version: start fresh
                return ConversationState()
    return ConversationState()


__all__ = ["STATE_KIND", "Awaiting", "ConversationState", "load_state", "route_message", "save_state"]
