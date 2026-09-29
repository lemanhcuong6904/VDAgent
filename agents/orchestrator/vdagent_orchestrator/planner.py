"""PLAN task (build spec 01 §6.2 PLN-3, §6.5): LLM 2 draft → build → check; one correction call; fallback when unavailable."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from vdagent_agentkit.llm import LlmRouter, LlmUsage
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.checker import RunState, Violation, check
from vdagent_orchestrator.fallback import fallback_plan
from vdagent_orchestrator.intent import IntentFrame
from vdagent_orchestrator.llm2 import draft_plan
from vdagent_orchestrator.planning import Plan, PlanDraft, build_plan


@dataclass
class PlanResult:
    plan: Plan | None
    frame: IntentFrame
    violations: list[Violation] = field(default_factory=list)
    llm_calls: int = 0
    usage: list[LlmUsage] = field(default_factory=list)
    reason: str | None = None  # PLAN_REJECTED | LLM_UNAVAILABLE | LLM_QUOTA_EXHAUSTED when plan is None


async def make_plan(frame: IntentFrame, *, router: LlmRouter | None, registry: CatalogRegistry, run_id: str, plan_id: str,
                    state: RunState, next_step_no: int, snapshot_pinned: bool, extra: dict[str, Any] | None = None,
                    known_produces: Mapping[str, Sequence[str]] = {}, allow_fallback: bool = True) -> PlanResult:
    result = PlanResult(None, frame)
    previous: PlanDraft | None = None
    for _ in range(2):  # the draft, then one correction (PLN-3)
        outcome = await draft_plan(frame, router=router, registry=registry, extra=extra, previous=previous,
                                   violations=[str(v) for v in result.violations])
        result.llm_calls += outcome.llm_calls
        result.usage += outcome.usage
        if outcome.draft is None:
            fallback = fallback_plan(frame, run_id=run_id, plan_id=plan_id, registry=registry,
                                     next_step_no=next_step_no) if allow_fallback else None
            if fallback is not None:
                result.plan, result.frame = fallback
                result.violations = []
            else:
                result.reason = outcome.error or "LLM_UNAVAILABLE"
            return result
        plan = build_plan(outcome.draft, run_id=run_id, plan_id=plan_id, registry=registry, next_step_no=next_step_no,
                          snapshot_pinned=snapshot_pinned, known_produces=known_produces)
        result.violations = check(plan, frame, registry, state)
        if not result.violations:
            result.plan, result.frame = plan, frame.model_copy(update={"plan_source": "LLM"})
            return result
        previous = outcome.draft
    result.reason = "PLAN_REJECTED"
    return result


__all__ = ["PlanResult", "make_plan"]
