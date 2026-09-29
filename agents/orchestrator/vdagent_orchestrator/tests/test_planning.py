"""Planning (build spec 01 §6: PLN-1…4, wiring §6.3, example PLN-EX-1 §6.4, fallback §6.5)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmError, LlmErrorCode, LlmRouter
from vdagent_contracts.intents import OutputKind, TaskKind
from vdagent_contracts.scope import UserContext
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.fallback import fallback_plan
from vdagent_orchestrator.intent import IntentDraft, IntentFrame, decide
from vdagent_orchestrator.llm2 import draft_plan
from vdagent_orchestrator.planning import DraftStep, PlanDraft, build_plan, step_spec

REGISTRY = CatalogRegistry.load()
SERVED = REGISTRY.served_kinds()
USER = UserContext.model_validate({"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-X"]}})


def frame(question: str, **fields: Any) -> IntentFrame:
    base: dict[str, Any] = {"scope_check": "ANALYSIS", "task_kinds": ["EXPLAIN"], "phenomena": ["bán chậm"],
                            "mentions": [{"text": "Landmark", "kind_hint": "ZONE"}]}
    base.update(fields)
    decision = decide(IntentDraft.model_validate(base), question=question, served=SERVED)
    assert decision.frame is not None
    return decision.frame


LANDMARK = frame("Tại sao phân khu Landmark bán chậm?")
SCOPE = {"mentions": [{"text": "Landmark", "kind_hint": "ZONE"}], "scope_all": False}


def step(step_id: str, agent: str, operation: str, inputs: list[str] = (), **spec: Any) -> DraftStep:  # type: ignore[assignment]
    return DraftStep(step_id=step_id, agent=agent, operation=operation, spec=spec, inputs=list(inputs),
                     objective=f"{operation} cho Landmark")


EX1 = PlanDraft(rationale="PLN-EX-1", steps=[
    step("B1", "data", "fetch_units", scope=SCOPE),
    step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold", "absorption_rate"]),
    step("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1", "T2"]),
    step("B4", "chart", "draw_chart", ["B2", "B3"]),
    step("B5", "report", "draft_report", ["B2", "B3", "B4"]),
])


def build(draft: PlanDraft = EX1, **kwargs: Any) -> Any:
    kwargs.setdefault("next_step_no", 1)
    return build_plan(draft, run_id="run-1", plan_id="plan-1", registry=REGISTRY, **kwargs)


def test_pln2_code_fills_owned_fields() -> None:
    plan = build()
    b1 = plan.step("B1")
    assert b1.idempotency_key == "plan-1:B1" and b1.deadline_s == 90  # catalog deadline (R-08)
    assert b1.spec["objective"] == "fetch_units cho Landmark"
    assert plan.catalog_versions == REGISTRY.versions()
    spec = step_spec(b1, plan, user_context=USER, question=LANDMARK.original_question, snapshot_id="snap-1")
    assert spec.user_context == USER and spec.snapshot_id == "snap-1" and spec.original_question == LANDMARK.original_question
    assert spec.run_id == "run-1" and spec.plan_id == "plan-1" and spec.operation == "fetch_units"
    # the LLM never sees user_context and cannot fill the fields code owns
    hostile = PlanDraft(rationale="", steps=[step("B1", "data", "fetch_units", scope=SCOPE, user_context={"projects": ["PRJ-Z"]},
                                                  run_id="evil", idempotency_key="x")])
    b1 = build(hostile).step("B1")
    assert not {"user_context", "run_id", "idempotency_key", "snapshot_id"} & set(b1.spec)


def test_pln4_step_ids_never_reused() -> None:
    plan = build(next_step_no=6)
    assert [s.step_id for s in plan.steps] == ["B6", "B7", "B8", "B9", "B10"]
    assert plan.step("B8").inputs == ["B6", "B7"] and plan.next_step_no == 11
    assert plan.step("B10").idempotency_key == "plan-1:B10"


def test_wiring_hard_vs_soft() -> None:
    draft = PlanDraft(rationale="", steps=[
        step("B1", "data", "fetch_units", scope=SCOPE),
        step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
        step("B3", "data", "fetch_unit_context", ["B1"]),
        step("B4", "insight", "explain_slow_moving", ["B1", "B2", "B3"], tasks=["T1", "T5"]),
    ])
    plan = build(draft)
    waits = {w.step_id: (w.mode, w.artifact_kinds) for w in plan.step("B4").waits}
    assert waits == {"B1": ("HARD", ["unit_set"]), "B2": ("HARD", ["metric_table"]), "B3": ("SOFT", ["unit_context"])}
    assert [(w.step_id, w.mode) for w in plan.step("B3").waits] == [("B1", "HARD")]  # waits on a Data step: no pin
    assert plan.step("B1").forward_to == ["B2", "B3", "B4"]


def test_pln_ex1_landmark_plan_waits_and_consumers() -> None:
    plan = build()
    modes = {s.step_id: {w.step_id: w.mode for w in s.waits} for s in plan.steps}
    assert modes == {"B1": {}, "B2": {"B1": "SOFT"}, "B3": {"B1": "HARD", "B2": "HARD"},
                     "B4": {"B2": "HARD", "B3": "SOFT"}, "B5": {"B2": "HARD", "B3": "SOFT", "B4": "SOFT"}}
    assert plan.step("B2").waits[0].snapshot_only and plan.step("B2").waits[0].artifact_kinds == []
    forwards = {s.step_id: s.forward_to for s in plan.steps}
    assert forwards == {"B1": ["B2", "B3"], "B2": ["B3", "B4", "B5"], "B3": ["B4", "B5"], "B4": ["B5"], "B5": []}
    assert [s.step_id for s in plan.openable()] == ["B1"]


def test_snapshot_pin_only_first_data_step_opens() -> None:
    pinned = build(snapshot_pinned=True)  # the run already has a snapshot: nothing to pin
    assert [s.step_id for s in pinned.openable()] == ["B1", "B2"]
    assert pinned.step("B2").waits == []
    unpinned = build()
    assert [w.snapshot_only for w in unpinned.step("B2").waits] == [True]


def test_fallback_single_aggregate_metrics_lookup_only() -> None:
    lookup = frame("DOM trung bình của Landmark là bao nhiêu?", task_kinds=["LOOKUP"], phenomena=[],
                   metrics=["avg_dom_unsold"], dimensions=["floor_band"], filters=["available"])
    result = fallback_plan(lookup, run_id="run-1", plan_id="plan-1", registry=REGISTRY, next_step_no=1)
    assert result is not None
    plan, new_frame = result
    assert [(s.step_id, s.agent, s.operation) for s in plan.steps] == [("B1", "data", "aggregate_metrics")]
    assert plan.step("B1").spec == {"objective": "DOM trung bình của Landmark là bao nhiêu?", "scope": SCOPE,
                                    "metrics": ["avg_dom_unsold"], "group_by": ["floor_band"], "filters": ["available"]}
    assert plan.source == "FALLBACK" and plan.limited_mode
    assert new_frame.requested_outputs == [OutputKind.CHAT_ANSWER] and new_frame.plan_source == "FALLBACK"
    assert any("chế độ giới hạn" in a for a in new_frame.assumptions)
    assert fallback_plan(LANDMARK, run_id="run-1", plan_id="plan-1", registry=REGISTRY, next_step_no=1) is None
    no_metric = frame("Landmark bao nhiêu?", task_kinds=["LOOKUP"], phenomena=[], metrics=[], filters=["available"])
    assert fallback_plan(no_metric, run_id="run-1", plan_id="plan-1", registry=REGISTRY, next_step_no=1) is None


def test_fallback_run_never_replans() -> None:
    lookup = frame("DOM trung bình của Landmark là bao nhiêu?", task_kinds=["LOOKUP"], phenomena=[], metrics=["avg_dom_unsold"])
    result = fallback_plan(lookup, run_id="run-1", plan_id="plan-1", registry=REGISTRY, next_step_no=1)
    assert result is not None and not result[0].may_replan
    assert build().may_replan


def test_llm2_prompt_and_unavailable() -> None:
    llm = FakeLLM([json.dumps(EX1.model_dump(mode="json"))])
    outcome = asyncio.run(draft_plan(LANDMARK, router=LlmRouter([llm]), registry=REGISTRY))
    assert outcome.draft == EX1 and outcome.llm_calls == 1
    system, user = llm.calls[0]["messages"]
    assert "explain_slow_moving" in system["content"] and "<data>" in user["content"]
    assert "user_context" not in system["content"] + user["content"] and "PRJ-X" not in system["content"] + user["content"]
    down = asyncio.run(draft_plan(LANDMARK, router=LlmRouter([FakeLLM([LlmError(LlmErrorCode.QUOTA_EXHAUSTED, "q")])]),
                                  registry=REGISTRY))
    assert down.draft is None and down.error == "LLM_QUOTA_EXHAUSTED"
    assert TaskKind.EXPLAIN in LANDMARK.task_kinds
