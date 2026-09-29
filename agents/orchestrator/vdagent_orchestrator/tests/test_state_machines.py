"""Run and step state machines (build spec 01 §14): every allowed edge passes, every other edge is refused."""

from __future__ import annotations

import itertools

import pytest

from vdagent_orchestrator.states import (
    RUN_STATES,
    RUN_TRANSITIONS,
    STEP_STATES,
    STEP_TRANSITIONS,
    InvalidTransition,
    next_run_status,
    run_transition,
    step_transition,
)

RUN_EDGES = {
    ("planning", "rejected"), ("planning", "input_required"), ("planning", "working"), ("planning", "failed"),
    ("input_required", "planning"), ("input_required", "working"), ("input_required", "replanning"),
    ("input_required", "canceled"),
    ("working", "replanning"), ("working", "input_required"), ("working", "completed"), ("working", "partial"),
    ("working", "failed"), ("working", "canceled"),
    ("replanning", "working"), ("replanning", "input_required"), ("replanning", "canceled"),
}
STEP_EDGES = {
    ("pending", "working"), ("pending", "skipped"), ("pending", "canceled"),
    ("working", "completed"), ("working", "input_required"), ("working", "failed"), ("working", "canceled"),
    ("input_required", "working"), ("input_required", "failed"), ("input_required", "canceled"),
}


def test_run_state_machine_every_edge() -> None:
    assert {(a, b) for a, targets in RUN_TRANSITIONS.items() for b in targets} == RUN_EDGES
    for a, b in itertools.product(RUN_STATES, repeat=2):
        if (a, b) in RUN_EDGES:
            assert run_transition(a, b) == b
        else:
            with pytest.raises(InvalidTransition):
                run_transition(a, b)


def test_step_state_machine_every_edge() -> None:
    assert {(a, b) for a, targets in STEP_TRANSITIONS.items() for b in targets} == STEP_EDGES
    for a, b in itertools.product(STEP_STATES, repeat=2):
        if (a, b) in STEP_EDGES:
            assert step_transition(a, b) == b
        else:
            with pytest.raises(InvalidTransition):
                step_transition(a, b)


def test_run_status_priority() -> None:
    assert next_run_status(input_pending=True, replan_pending=True) == "input_required"
    assert next_run_status(input_pending=False, replan_pending=True) == "replanning"
    assert next_run_status(input_pending=False, replan_pending=False) == "working"
