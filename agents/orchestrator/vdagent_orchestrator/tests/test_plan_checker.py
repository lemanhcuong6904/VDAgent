"""Plan checker, 12 rules (build spec 01 §7) and PLN-3 correction (§6.2); V25 from the source §13."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmError, LlmErrorCode, LlmRouter
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import OutputKind
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.checker import ExistingStep, RunState, check
from vdagent_orchestrator.intent import IntentDraft, IntentFrame, decide
from vdagent_orchestrator.planner import make_plan
from vdagent_orchestrator.planning import DraftStep, Plan, PlanDraft, build_plan

REGISTRY = CatalogRegistry.load()
SCOPE = {"mentions": [{"text": "Landmark", "kind_hint": "ZONE"}], "scope_all": False}


def _frame(**fields: Any) -> IntentFrame:
    base: dict[str, Any] = {"scope_check": "ANALYSIS", "task_kinds": ["EXPLAIN"], "phenomena": ["bán chậm"],
                            "mentions": [{"text": "Landmark", "kind_hint": "ZONE"}]}
    base.update(fields)
    decision = decide(IntentDraft.model_validate(base), question="Tại sao phân khu Landmark bán chậm?",
                      served=REGISTRY.served_kinds())
    assert decision.frame is not None
    return decision.frame


FRAME = _frame()


def s(step_id: str, agent: str, operation: str, inputs: list[str] | None = None, replaces: str | None = None,
      **spec: Any) -> DraftStep:
    return DraftStep(step_id=step_id, agent=agent, operation=operation, spec=spec, inputs=inputs or [],
                     objective=f"{operation} Landmark", replaces=replaces)


def data_steps() -> list[DraftStep]:
    return [s("B1", "data", "fetch_units", scope=SCOPE),
            s("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])]


def full() -> list[DraftStep]:
    return [*data_steps(), s("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]),
            s("B4", "chart", "draw_chart", ["B2", "B3"]), s("B5", "report", "draft_report", ["B2", "B3", "B4"])]


def plan_of(steps: list[DraftStep], *, drop: list[str] | None = None, next_step_no: int = 1,
            known: dict[str, list[str]] | None = None) -> Plan:
    return build_plan(PlanDraft(steps=steps, drop=drop or []), run_id="run-1", plan_id="plan-1", registry=REGISTRY,
                      next_step_no=next_step_no, known_produces=known or {})


def codes(plan: Plan, frame: IntentFrame = FRAME, state: RunState | None = None) -> set[str]:
    return {v.code for v in check(plan, frame, REGISTRY, state or RunState())}


Case = Callable[[], tuple[Plan, IntentFrame, RunState]]
DONE_DATA = RunState(steps=(ExistingStep("B1", "data", "fetch_units", "completed"),
                            ExistingStep("B2", "data", "aggregate_metrics", "completed")), step_count=2)
FAILED_INSIGHT = RunState(steps=(*DONE_DATA.steps, ExistingStep("B3", "insight", "explain_slow_moving", "failed",
                                                                error_class=ErrorClass.WRONG_RESULT, owner_replan="R1")),
                          step_count=3, replan_id="R1")
KNOWN = {"B1": ["unit_set", "dq_report"], "B2": ["metric_table", "dq_report"]}


OK: dict[str, Case] = {
    "BAD_STEP_ID": lambda: (plan_of(full()), FRAME, RunState()),
    "UNKNOWN_OPERATION": lambda: (plan_of(full()), FRAME, RunState()),
    "SPEC_INVALID": lambda: (plan_of(full()), FRAME, RunState()),
    "MISSING_REQUIRED_INPUT": lambda: (  # inputs from finished steps of the run
        plan_of([s("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]), s("B4", "chart", "draw_chart", ["B2"]),
                 s("B5", "report", "draft_report", ["B2"])], next_step_no=3, known=KNOWN), FRAME, DONE_DATA),
    "BAD_WIRING": lambda: (plan_of(full()), FRAME, RunState()),
    "CYCLE": lambda: (plan_of(full()), FRAME, RunState()),
    "OUTPUT_NOT_COVERED": lambda: (  # the report is owned by a queued REPLAN task: "will exist"
        plan_of([*data_steps(), s("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]),
                 s("B4", "chart", "draw_chart", ["B2", "B3"])]), FRAME, RunState(will_exist_outputs=frozenset({OutputKind.REPORT}))),
    "TASK_MIN_STEPS": lambda: (plan_of(full()), FRAME, RunState()),
    "MENTION_NOT_IN_REQUEST": lambda: (plan_of(full()), FRAME, RunState()),
    "BAD_DROP": lambda: (plan_of([s("B4", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"])], drop=["B3"],
                                 next_step_no=4, known=KNOWN), _frame(requested_outputs=["CHAT_ANSWER"]),
                         RunState(steps=(*DONE_DATA.steps, ExistingStep("B3", "insight", "describe_patterns", "pending")),
                                  step_count=3)),
    "BAD_REPLACEMENT": lambda: (plan_of([s("B4", "insight", "explain_slow_moving", ["B1", "B2"], replaces="B3", tasks=["T1"])],
                                        next_step_no=4, known=KNOWN), _frame(requested_outputs=["CHAT_ANSWER"]), FAILED_INSIGHT),
    "PLAN_LIMIT_EXCEEDED": lambda: (plan_of(full(), next_step_no=6), FRAME,
                                    RunState(steps=tuple(ExistingStep(f"B{i}", "data", "fetch_units", "completed") for i in range(1, 6)),
                                             step_count=5)),
}

VIOLATION: dict[str, Case] = {
    "BAD_STEP_ID": lambda: (plan_of(full()), FRAME, RunState(steps=(ExistingStep("B1", "data", "fetch_units", "failed"),),
                                                             step_count=1)),
    "UNKNOWN_OPERATION": lambda: (plan_of([*full(), s("B6", "data", "drop_all")]), FRAME, RunState()),
    "SPEC_INVALID": lambda: (plan_of([s("B1", "data", "fetch_units", scope=SCOPE),
                                      s("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["revenue"]), *full()[2:]]),
                             FRAME, RunState()),
    "MISSING_REQUIRED_INPUT": lambda: (plan_of([*data_steps(), s("B3", "insight", "explain_slow_moving", ["B1"], tasks=["T1"]),
                                                *full()[3:]]), FRAME, RunState()),
    "BAD_WIRING": lambda: (plan_of([*data_steps(), s("B3", "insight", "explain_slow_moving", ["B1", "B2", "B9"], tasks=["T1"]),
                                    *full()[3:]]), FRAME, RunState()),
    "CYCLE": lambda: (plan_of([s("B1", "data", "fetch_units", ["B3"], scope=SCOPE), *full()[1:]]), FRAME, RunState()),
    "OUTPUT_NOT_COVERED": lambda: (plan_of([*data_steps(), s("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]),
                                            s("B4", "chart", "draw_chart", ["B2", "B3"])]), FRAME, RunState()),
    "TASK_MIN_STEPS": lambda: (plan_of([*data_steps(), s("B3", "chart", "draw_chart", ["B2"]),
                                        s("B4", "report", "draft_report", ["B2"])]), FRAME, RunState()),
    "MENTION_NOT_IN_REQUEST": lambda: (plan_of([s("B1", "data", "fetch_units", scope={"mentions": [
        {"text": "Aqua 1", "kind_hint": "ZONE"}], "scope_all": False}), *full()[1:]]), FRAME, RunState()),
    "BAD_DROP": lambda: (plan_of([s("B4", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"])], drop=["B2"],
                                 next_step_no=4, known=KNOWN), _frame(requested_outputs=["CHAT_ANSWER"]), DONE_DATA),
    "BAD_REPLACEMENT": lambda: (plan_of([s("B4", "chart", "draw_chart", ["B2"], replaces="B3"),
                                         s("B5", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"])],
                                        next_step_no=4, known=KNOWN), _frame(requested_outputs=["CHAT_ANSWER"]), FAILED_INSIGHT),
    "PLAN_LIMIT_EXCEEDED": lambda: (plan_of(full(), next_step_no=7), FRAME,
                                    RunState(steps=tuple(ExistingStep(f"B{i}", "data", "fetch_units", "completed") for i in range(1, 7)),
                                             step_count=6)),
}


@pytest.mark.parametrize("rule", sorted(OK))
def test_plan_checker_rule_ok(rule: str) -> None:
    plan, frame, state = OK[rule]()
    assert rule not in codes(plan, frame, state)


@pytest.mark.parametrize("rule", sorted(VIOLATION))
def test_plan_checker_rule_violation(rule: str) -> None:
    plan, frame, state = VIOLATION[rule]()
    assert rule in codes(plan, frame, state)


def test_plan_checker_full_plan_is_clean() -> None:
    assert check(plan_of(full()), FRAME, REGISTRY, RunState()) == []


def test_replacement_class_and_used_part() -> None:
    transient = RunState(steps=(*DONE_DATA.steps, ExistingStep("B3", "insight", "explain_slow_moving", "failed",
                                                               error_class=ErrorClass.TRANSIENT, owner_replan="R1")),
                         step_count=3, replan_id="R1")
    used = RunState(steps=(*DONE_DATA.steps, ExistingStep("B3", "insight", "explain_slow_moving", "failed",
                                                          error_class=ErrorClass.NO_DATA, owner_replan="R1", replan_used=True)),
                    step_count=3, replan_id="R1")
    frame = _frame(requested_outputs=["CHAT_ANSWER"])
    replacement = plan_of([s("B4", "insight", "explain_slow_moving", ["B1", "B2"], replaces="B3", tasks=["T1"])],
                          next_step_no=4, known=KNOWN)
    assert "BAD_REPLACEMENT" in codes(replacement, frame, transient)
    assert "BAD_REPLACEMENT" in codes(replacement, frame, used)


def _plan_json(steps: list[DraftStep]) -> str:
    return json.dumps(PlanDraft(steps=steps, rationale="r").model_dump(mode="json"))


def _make(llm: FakeLLM | None, frame: IntentFrame = FRAME) -> Any:
    return asyncio.run(make_plan(frame, router=LlmRouter([llm]) if llm else None, registry=REGISTRY, run_id="run-1",
                                 plan_id="plan-1", state=RunState(), next_step_no=1, snapshot_pinned=False))


def test_v25_task_min_steps_blocks_then_one_repair() -> None:
    no_insight = [*data_steps(), s("B3", "chart", "draw_chart", ["B2"]), s("B4", "report", "draft_report", ["B2"])]
    llm = FakeLLM([_plan_json(no_insight), _plan_json(full())])
    result = _make(llm)
    assert result.plan is not None and result.llm_calls == 2 and result.plan.source == "LLM"
    correction = llm.calls[1]["messages"][-1]["content"]
    assert "TASK_MIN_STEPS" in correction and "EXPLAIN" in correction


def test_pln3_still_invalid_plan_rejected() -> None:
    no_insight = [*data_steps(), s("B3", "chart", "draw_chart", ["B2"]), s("B4", "report", "draft_report", ["B2"])]
    result = _make(FakeLLM([_plan_json(no_insight), _plan_json(no_insight)]))
    assert result.plan is None and result.reason == "PLAN_REJECTED" and result.llm_calls == 2
    assert {v.code for v in result.violations} == {"TASK_MIN_STEPS"}


def test_planning_unavailable_uses_fallback_or_fails() -> None:
    down = FakeLLM([LlmError(LlmErrorCode.TRANSIENT, "x")])
    assert _make(down).reason == "LLM_UNAVAILABLE" and _make(None).plan is None
    lookup = _frame(task_kinds=["LOOKUP"], phenomena=[], metrics=["avg_dom_unsold"])
    result = _make(FakeLLM([LlmError(LlmErrorCode.TRANSIENT, "x")]), lookup)
    assert result.plan is not None and result.plan.source == "FALLBACK" and result.frame.plan_source == "FALLBACK"
