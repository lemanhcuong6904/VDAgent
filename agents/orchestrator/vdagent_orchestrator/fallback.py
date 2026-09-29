"""Fallback plan (build spec 01 §6.5): planning LLM unavailable, a LOOKUP with a catalog metric → one aggregate_metrics step."""

from __future__ import annotations

from vdagent_contracts.intents import OutputKind, TaskKind
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.intent import IntentFrame
from vdagent_orchestrator.planning import DraftStep, Plan, PlanDraft, build_plan

LIMITED_MODE = "Hệ thống đang ở chế độ giới hạn: chỉ tra số liệu, trả lời trong chat."


def fallback_plan(frame: IntentFrame, *, run_id: str, plan_id: str, registry: CatalogRegistry,
                  next_step_no: int) -> tuple[Plan, IntentFrame] | None:
    vocab = registry.vocabulary()
    metrics = [m for m in frame.metrics if m in vocab["metrics"]]
    if frame.task_kinds != [TaskKind.LOOKUP] or not metrics:
        return None
    spec = {"scope": {"mentions": [m.model_dump() for m in frame.mentions], "scope_all": frame.scope_all},
            "metrics": metrics, "group_by": [d for d in frame.dimensions if d in vocab["dimensions"]],
            "filters": [f for f in frame.filters if f in vocab["filters"]]}
    draft = PlanDraft(rationale="fallback", steps=[DraftStep(step_id="B1", agent="data", operation="aggregate_metrics",
                                                             spec=spec, objective=frame.original_question[:300])])
    plan = build_plan(draft, run_id=run_id, plan_id=plan_id, registry=registry, next_step_no=next_step_no,
                      snapshot_pinned=True, source="FALLBACK", limited_mode=True)
    limited = frame.model_copy(update={"requested_outputs": [OutputKind.CHAT_ANSWER], "plan_source": "FALLBACK",
                                       "assumptions": [*frame.assumptions, LIMITED_MODE]})
    return plan, limited


__all__ = ["LIMITED_MODE", "fallback_plan"]
