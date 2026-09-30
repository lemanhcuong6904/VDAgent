"""The Orchestrator's executable plan (WS5): steps, dependencies and the code-enforced rules they must satisfy.

A plan is data. `validate_plan` rejects anything the executor must not run:
- step ids `B<n>`, unique; at least one step;
- every agent/operation is declared in its frozen catalog (contracts/vdagent_contracts/catalogs/<agent>.json) — the
  Orchestrator itself, Report (WS6) and unknown agents are not targets;
- dependencies exist, form no cycle, and inputs are only taken from declared dependencies;
- exactly one snapshot and one semantic config version for the whole run.
It returns the execution waves (steps whose dependencies are all in earlier waves), e.g. [[B1], [B2, B3], [B4]].
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from vdagent_contracts.catalog import AgentCatalog

STEP_ID = re.compile(r"^B[1-9][0-9]*$")
TARGET_AGENTS = ("data", "insight", "compare", "chart", "report")


class PlanError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class InputBinding:
    """Take the artifacts of these types from the (completed) output refs of `from_step`."""

    from_step: str
    artifact_types: tuple[str, ...]


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    agent: str
    operation: str
    spec: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()
    dependency_mode: Literal["all", "any"] = "all"  # any = at least one dependency must have completed
    inputs: tuple[InputBinding, ...] = ()


@dataclass(frozen=True)
class Plan:
    plan_id: str
    run_id: str
    snapshot_id: str
    semantic_config_version: str
    question: str
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)  # who proposed the plan (LLM planner); {} = code

    def step(self, step_id: str) -> PlanStep:
        return next(s for s in self.steps if s.step_id == step_id)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        if not self.provenance:
            del data["provenance"]  # deterministic plans are recorded exactly as before
        return data


def validate_plan(plan: Plan, catalogs: Mapping[str, AgentCatalog]) -> list[list[str]]:
    if not plan.snapshot_id:
        raise PlanError("SNAPSHOT_REQUIRED", "a run pins exactly one snapshot")
    if not plan.semantic_config_version:
        raise PlanError("SEMANTIC_VERSION_REQUIRED", "a run pins exactly one semantic config version")
    if not plan.steps:
        raise PlanError("EMPTY_PLAN", "a plan needs at least one step")
    ids: set[str] = set()
    for step in plan.steps:
        if not STEP_ID.fullmatch(step.step_id):
            raise PlanError("INVALID_STEP_ID", f"{step.step_id!r} is not B<n>")
        if step.step_id in ids:
            raise PlanError("DUPLICATE_STEP", f"{step.step_id} appears twice")
        ids.add(step.step_id)
        if step.agent not in TARGET_AGENTS or step.agent not in catalogs:
            raise PlanError("UNSUPPORTED_AGENT", f"{step.agent!r} is not a DAG target")
        try:
            catalogs[step.agent].operation(step.operation)
        except KeyError:
            raise PlanError("UNSUPPORTED_OPERATION", f"{step.agent} has no operation {step.operation!r}") from None
    for step in plan.steps:
        for dep in step.depends_on:
            if dep not in ids:
                raise PlanError("UNKNOWN_DEPENDENCY", f"{step.step_id} depends on unknown {dep}")
        for binding in step.inputs:
            if binding.from_step not in step.depends_on:
                raise PlanError("INPUT_NOT_FROM_DEPENDENCY", f"{step.step_id} takes inputs from {binding.from_step}, not a dependency")
    waves: list[list[str]] = []
    done: set[str] = set()
    pending = [s for s in plan.steps]
    while pending:
        ready = [s.step_id for s in pending if set(s.depends_on) <= done]
        if not ready:
            raise PlanError("CYCLE", "dependencies form a cycle: " + ", ".join(s.step_id for s in pending))
        waves.append(ready)
        done |= set(ready)
        pending = [s for s in pending if s.step_id not in done]
    return waves
