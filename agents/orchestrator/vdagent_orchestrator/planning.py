"""Plans (build spec 01 §6.1, PLN-2, PLN-4): the LLM drafts steps; code numbers them, fills the fields it owns and wires them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vdagent_contracts.envelope import ArtifactRef
from vdagent_contracts.messages import AnsweredChoice, StepSpec
from vdagent_contracts.scope import UserContext
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.wiring import Node, WaitEntry, wire

STEP_ID = r"^B[1-9][0-9]*$"
# PLN-2: fields code fills; the LLM's values for them are discarded
CODE_OWNED = {"contract", "contract_version", "catalog_version", "run_id", "plan_id", "step_id", "idempotency_key",
              "user_context", "original_question", "snapshot_id", "semantic_config_version", "consumer_steps",
              "deadline_s", "input_refs", "released_inputs", "answered_choices"}


class DraftStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(pattern=STEP_ID)
    agent: str
    operation: str
    spec: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    objective: str = Field(max_length=300)
    replaces: str | None = None


class PlanDraft(BaseModel):
    """What LLM 2 returns."""

    model_config = ConfigDict(extra="forbid")
    steps: list[DraftStep]
    drop: list[str] = Field(default_factory=list)
    rationale: str = ""


class PlannedStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: str
    agent: str
    operation: str
    spec: dict[str, Any]
    inputs: list[str]
    objective: str
    replaces: str | None = None
    waits: list[WaitEntry] = Field(default_factory=list)
    forward_to: list[str] = Field(default_factory=list)
    deadline_s: int
    idempotency_key: str
    plan_version: int = 1


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    plan_id: str
    version: int = 1
    steps: list[PlannedStep]
    drop: list[str] = Field(default_factory=list)
    rationale: str = ""
    source: Literal["LLM", "FALLBACK"] = "LLM"
    limited_mode: bool = False
    catalog_versions: dict[str, str] = Field(default_factory=dict)
    next_step_no: int

    def step(self, step_id: str) -> PlannedStep:
        return next(s for s in self.steps if s.step_id == step_id)

    def openable(self) -> list[PlannedStep]:
        """Steps the Orchestrator starts right away (no wait at all)."""
        return [s for s in self.steps if not s.waits]

    @property
    def may_replan(self) -> bool:
        return self.source != "FALLBACK"  # §6.5: a fallback run never replans


def _owned_spec(draft: DraftStep, schema: Mapping[str, Any]) -> dict[str, Any]:
    spec = {k: v for k, v in draft.spec.items() if k not in CODE_OWNED}
    if "objective" in schema.get("properties", {}):
        spec["objective"] = draft.objective
    return spec


def build_plan(draft: PlanDraft, *, run_id: str, plan_id: str, registry: CatalogRegistry, next_step_no: int,
               snapshot_pinned: bool = False, version: int = 1, source: Literal["LLM", "FALLBACK"] = "LLM",
               limited_mode: bool = False, known_produces: Mapping[str, Sequence[str]] = {}) -> Plan:
    """PLN-2/PLN-4: renumber draft ids from `next_step_no` (references follow), fill code-owned fields, wire."""
    ids = {s.step_id: f"B{next_step_no + i}" for i, s in enumerate(draft.steps)}
    renamed = [s.model_copy(update={"step_id": ids[s.step_id], "inputs": [ids.get(i, i) for i in s.inputs]})
               for s in draft.steps]
    waits, forwards = wire([Node(s.step_id, s.agent, s.operation, tuple(s.inputs)) for s in renamed], registry,
                           snapshot_pinned=snapshot_pinned, known_produces=known_produces)
    steps = []
    for s in renamed:
        try:
            op = registry.operation(s.agent, s.operation)
            schema, deadline = op.input_schema, op.deadline_s
        except KeyError:  # unknown operation: kept so the checker can report it
            schema, deadline = {}, 120
        steps.append(PlannedStep(step_id=s.step_id, agent=s.agent, operation=s.operation, spec=_owned_spec(s, schema),
                                 inputs=s.inputs, objective=s.objective, replaces=s.replaces, waits=waits[s.step_id],
                                 forward_to=forwards.get(s.step_id, []), deadline_s=deadline,
                                 idempotency_key=f"{plan_id}:{s.step_id}", plan_version=version))
    return Plan(run_id=run_id, plan_id=plan_id, version=version, steps=steps, drop=draft.drop, rationale=draft.rationale,
                source=source, limited_mode=limited_mode, catalog_versions=registry.versions(),
                next_step_no=next_step_no + len(draft.steps))


def step_spec(step: PlannedStep, plan: Plan, *, user_context: UserContext, question: str, snapshot_id: str | None,
              semantic_config_version: str | None = None, input_refs: Sequence[ArtifactRef] = (),
              released_inputs: Sequence[str] = (), answered_choices: Sequence[AnsweredChoice] = ()) -> StepSpec:
    """The StepSpec sent to the agent: identity, user context and snapshot come from the run, never from the LLM."""
    return StepSpec(run_id=plan.run_id, plan_id=plan.plan_id, step_id=step.step_id, idempotency_key=step.idempotency_key,
                    operation=step.operation, spec=step.spec, user_context=user_context, snapshot_id=snapshot_id,
                    semantic_config_version=semantic_config_version, input_refs=list(input_refs),
                    released_inputs=list(released_inputs), answered_choices=list(answered_choices),
                    deadline_s=step.deadline_s, original_question=question)


__all__ = ["CODE_OWNED", "DraftStep", "Plan", "PlanDraft", "PlannedStep", "build_plan", "step_spec"]
