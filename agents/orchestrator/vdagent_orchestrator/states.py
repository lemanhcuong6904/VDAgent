"""Run and step state machines (build spec 01 §14), enforced with transition tables."""

from __future__ import annotations

RUN_STATES = ("planning", "input_required", "working", "replanning", "completed", "partial", "failed", "canceled",
              "rejected")
STEP_STATES = ("pending", "working", "input_required", "completed", "failed", "skipped", "canceled")

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "planning": frozenset({"rejected", "input_required", "working", "failed"}),
    "input_required": frozenset({"planning", "working", "replanning", "canceled"}),
    "working": frozenset({"replanning", "input_required", "completed", "partial", "failed", "canceled"}),
    "replanning": frozenset({"working", "input_required", "canceled"}),
}
STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"working", "skipped", "canceled"}),
    "working": frozenset({"completed", "input_required", "failed", "canceled"}),
    "input_required": frozenset({"working", "failed", "canceled"}),
}
RUN_TERMINAL = frozenset({"completed", "partial", "failed", "canceled", "rejected"})
STEP_TERMINAL = frozenset({"completed", "failed", "skipped", "canceled"})


class InvalidTransition(ValueError):
    pass


def _move(table: dict[str, frozenset[str]], what: str, current: str, new: str) -> str:
    if new not in table.get(current, frozenset()):
        raise InvalidTransition(f"{what}: {current} → {new} is not allowed")
    return new


def run_transition(current: str, new: str) -> str:
    return _move(RUN_TRANSITIONS, "run", current, new)


def step_transition(current: str, new: str) -> str:
    return _move(STEP_TRANSITIONS, "step", current, new)


def next_run_status(*, input_pending: bool, replan_pending: bool) -> str:
    """Priority when several apply: input_required > replanning > working."""
    if input_pending:
        return "input_required"
    return "replanning" if replan_pending else "working"


__all__ = ["RUN_STATES", "RUN_TERMINAL", "RUN_TRANSITIONS", "STEP_STATES", "STEP_TERMINAL", "STEP_TRANSITIONS",
           "InvalidTransition", "next_run_status", "run_transition", "step_transition"]
