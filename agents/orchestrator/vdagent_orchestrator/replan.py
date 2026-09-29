"""Tier 2 — replanning (build spec 01 §11), run inside the turn (no task queue, DEC-026).

Every REPLAN item left by the dispatcher is merged into one LLM 2 call (RPL-3); at most `MAX_REPLANS` per run and one
LLM replacement per part (RPL-1). The new plan is checked against the run (12 rules, one correction) and applied:
new steps join the run, waiters of replaced steps are rewired, dropped steps are skipped or flagged, failed steps the
plan did not address are reported directly. Abandoned → WRONG_RESULT goes to tier 3, other classes are reported directly (RPL-7).
"""

from __future__ import annotations

from typing import Any

from vdagent_agentkit.llm import LlmRouter
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.checker import ExistingStep, RunState
from vdagent_orchestrator.dispatcher import AWAITING, escalate, maybe_close, report_direct, rewire
from vdagent_orchestrator.planner import make_plan
from vdagent_orchestrator.planning import Plan
from vdagent_orchestrator.records import RunRecord, StepRecord, record_for
from vdagent_orchestrator.states import next_run_status

MAX_REPLANS = 2


def tier2_available(run: RunRecord, router: LlmRouter | None) -> bool:
    return router is not None and run.plan.may_replan and run.replan_count < MAX_REPLANS


def _checker_state(run: RunRecord, replan_id: str) -> RunState:
    return RunState(
        steps=tuple(ExistingStep(s.step_id, s.agent, s.operation, s.status, error_class=s.error_class,
                                 owner_replan=s.owner_replan, replan_used=s.replan_used,
                                 awaiting=bool(set(s.flags) & AWAITING), dropped="dropped" in s.flags)
                    for s in run.ordered()),
        step_count=len(run.steps), replan_id=replan_id)


def _context(run: RunRecord, items: list[StepRecord]) -> dict[str, Any]:
    """PLN-1 for REPLAN: step states and failure reasons only — never summaries or package contents."""
    return {
        "next_step_id": f"B{run.plan.next_step_no}",
        "current_steps": [{"step_id": s.step_id, "agent": s.agent, "operation": s.operation, "status": s.status,
                           "error_code": s.error_code, "error_class": s.error_class.value if s.error_class else None,
                           "inputs": run.plan.step(s.step_id).inputs} for s in run.ordered()],
        "replan_items": [{"step_id": s.step_id, "agent": s.agent, "operation": s.operation, "error_code": s.error_code,
                          "error_class": s.error_class.value if s.error_class else None, "reason": s.error_message}
                         for s in items],
    }


def _abandon(run: RunRecord, items: list[StepRecord], reason: str) -> None:
    run.event("REPLAN_ABANDONED", steps=[s.step_id for s in items], reason=reason)
    for step in items:
        escalate(run, step)


def _apply(run: RunRecord, plan: Plan, items: list[StepRecord], replan_id: str) -> None:
    replaced = {s.replaces: s.step_id for s in plan.steps if s.replaces}
    run.plan = run.plan.model_copy(update={"steps": [*run.plan.steps, *plan.steps], "drop": [*run.plan.drop, *plan.drop],
                                           "version": run.plan.version + 1, "next_step_no": plan.next_step_no})
    for planned in plan.steps:
        record = record_for(planned)
        if planned.replaces:
            old = run.steps[planned.replaces]
            record.part_id, record.replan_used = old.part_id, True
            old.replan_used = True
        run.steps[planned.step_id] = record
    for old_id, new_id in replaced.items():  # REWIRE waiters F → F'
        rewire(run, old_id, new_id)
    for dropped_id in plan.drop:
        dropped = run.steps[dropped_id]
        dropped.flags = [f for f in dropped.flags if f not in AWAITING] + ["dropped"]
        if dropped.status == "pending":
            dropped.status = "skipped"
        if dropped_id not in replaced:
            report_direct(run, dropped)
    for step in items:
        if step.owner_replan == replan_id and step.step_id not in replaced and step.step_id not in plan.drop:
            escalate(run, step)  # the plan did not address it
        else:
            step.flags = [f for f in step.flags if f not in AWAITING]
    run.event("PLAN_REVISED", plan_version=run.plan.version, replan_id=replan_id)


async def replan(run: RunRecord, *, router: LlmRouter | None, registry: CatalogRegistry) -> RunRecord:
    items = [run.steps[p["step_id"]] for p in run.pending if p["kind"] == "REPLAN"]
    if not items or run.finished:
        return run
    run.pending = [p for p in run.pending if p["kind"] != "REPLAN"]
    if not tier2_available(run, router):
        _abandon(run, items, "LLM_UNAVAILABLE" if router is None else "REPLAN_LIMIT")
        maybe_close(run)
        return run
    run.replan_count += 1
    replan_id = f"R{run.replan_count}"
    run.status = "replanning"
    run.event("REPLAN_REQUESTED", replan_id=replan_id, steps=[s.step_id for s in items])
    for step in items:
        step.owner_replan = replan_id
    known = {}
    for s in run.steps.values():
        try:
            known[s.step_id] = registry.operation(s.agent, s.operation).produces
        except KeyError:
            known[s.step_id] = []
    result = await make_plan(run.frame, router=router, registry=registry, run_id=run.run_id, plan_id=run.plan.plan_id,
                             state=_checker_state(run, replan_id), next_step_no=run.plan.next_step_no,
                             snapshot_pinned=run.snapshot_id is not None, extra=_context(run, items), known_produces=known,
                             allow_fallback=False)
    run.llm_calls += result.llm_calls
    if result.plan is None:
        _abandon(run, items, result.reason or "PLAN_REJECTED")
    else:
        _apply(run, result.plan, items, replan_id)
    run.status = next_run_status(input_pending=any(p["kind"] == "INPUT" for p in run.pending),
                                 replan_pending=any(p["kind"] == "REPLAN" for p in run.pending))
    maybe_close(run)
    return run


__all__ = ["MAX_REPLANS", "replan", "tier2_available"]
