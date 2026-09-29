"""Run state kept between turns (N8, R1): one serializable record per run, stored in `ctx.memory` by the plugin."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vdagent_contracts.envelope import ArtifactRef
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.reports import ReportQuestion
from vdagent_contracts.scope import UserContext
from vdagent_orchestrator.intent import IntentFrame
from vdagent_orchestrator.planning import Plan, PlannedStep
from vdagent_orchestrator.wiring import WaitEntry, step_no


class StepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    agent: str
    operation: str
    status: str = "pending"
    waits: list[WaitEntry] = Field(default_factory=list)
    released: list[str] = Field(default_factory=list)  # SOFT waits that ended without a package
    refs: list[ArtifactRef] = Field(default_factory=list)
    summary: str = ""
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)
    data_confidence: str | None = None
    error_code: str | None = None
    error_class: ErrorClass | None = None
    error_message: str | None = None
    flags: list[str] = Field(default_factory=list)  # awaiting_replan | awaiting_decision | dropped
    question: ReportQuestion | None = None
    resend: bool = False  # answered: send again with the choice (§10.4)
    replan_used: bool = False
    owner_replan: str | None = None
    part_id: str | None = None
    replaces: str | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    plan: Plan
    frame: IntentFrame
    user_context: UserContext
    status: str = "working"
    snapshot_id: str | None = None
    semantic_config_version: str | None = None
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    ops_alerts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    pending: list[dict[str, Any]] = Field(default_factory=list)  # INPUT / REPLAN / DECISION waiting for a handler
    agent_questions: int = 0
    replan_count: int = 0
    llm_calls: int = 0
    decision_asked: bool = False
    retry_reserve_used: int = 0
    sales_ops_inputs: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None  # RunSummary (close.py), set once when the run closes
    summary_artifact_id: str | None = None  # run_summary written (lineage.py)
    finished: bool = False

    def ordered(self) -> list[StepRecord]:
        return sorted(self.steps.values(), key=lambda s: step_no(s.step_id))

    def event(self, name: str, **payload: Any) -> None:
        self.events.append({"event": name, **payload})


def record_for(step: PlannedStep) -> StepRecord:
    return StepRecord(step_id=step.step_id, agent=step.agent, operation=step.operation, waits=list(step.waits),
                      part_id=step.step_id, replaces=step.replaces)


def new_run(plan: Plan, frame: IntentFrame, *, user_context: UserContext, snapshot_id: str | None = None,
            semantic_config_version: str | None = None) -> RunRecord:
    run = RunRecord(run_id=plan.run_id, plan=plan, frame=frame, user_context=user_context, snapshot_id=snapshot_id,
                    semantic_config_version=semantic_config_version,
                    steps={s.step_id: record_for(s) for s in plan.steps})
    run.event("PLAN_DISPATCHED", plan_version=plan.version, source=plan.source)
    return run


__all__ = ["RunRecord", "StepRecord", "new_run", "record_for"]
