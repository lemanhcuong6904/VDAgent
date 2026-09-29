"""Propagation of a failed step to the steps waiting on it (build spec 01 §10.2). Pure.

| outcome of F                     | HARD waiter    | SOFT waiter |
| failed + awaiting replan/decision | keep waiting  | keep waiting |
| replaced by F'                   | REWIRE F→F'    | REWIRE F→F' |
| reported directly / current kept | SKIP + CANCEL  | RELEASE     |

A skipped step counts as "reported directly" for its own waiters, recursively. Terminal steps are left alone.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from vdagent_orchestrator.wiring import WaitEntry

NON_TERMINAL = {"pending", "working", "input_required"}


@dataclass(frozen=True)
class StepView:
    step_id: str
    status: str
    waits: tuple[WaitEntry, ...] = ()


@dataclass(frozen=True)
class Action:
    kind: Literal["KEEP_WAITING", "REWIRE", "SKIP_CANCEL", "RELEASE"]
    step_id: str
    from_step: str
    to_step: str | None = None


def propagate(failed: str, outcome: Literal["AWAITING", "REPLACED", "DIRECT"], steps: Sequence[StepView], *,
              replacement: str | None = None) -> list[Action]:
    status = {s.step_id: s.status for s in steps}

    def waiters(on: str) -> list[tuple[StepView, WaitEntry]]:
        return [(s, w) for s in steps if status[s.step_id] in NON_TERMINAL for w in s.waits if w.step_id == on]

    if outcome == "AWAITING":
        return [Action("KEEP_WAITING", s.step_id, failed) for s, _ in waiters(failed)]
    if outcome == "REPLACED":
        assert replacement is not None
        return [Action("REWIRE", s.step_id, failed, replacement) for s, _ in waiters(failed)]
    actions: list[Action] = []
    queue = deque([failed])
    while queue:
        current = queue.popleft()
        for step, wait in waiters(current):
            if wait.mode == "HARD":
                status[step.step_id] = "skipped"
                actions.append(Action("SKIP_CANCEL", step.step_id, current))
                queue.append(step.step_id)
            else:
                actions.append(Action("RELEASE", step.step_id, current))
    return actions


__all__ = ["Action", "StepView", "propagate"]
