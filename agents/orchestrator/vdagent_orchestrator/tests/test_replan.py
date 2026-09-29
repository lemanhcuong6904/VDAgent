"""Tier 2 replanning (build spec 01 §11 RPL-1…7; source §13 V4, V16, V17, V19, V23)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmError, LlmErrorCode, LlmRouter
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_orchestrator.dispatcher import drive
from vdagent_orchestrator.planning import DraftStep, PlanDraft
from vdagent_orchestrator.records import RunRecord
from vdagent_orchestrator.replan import MAX_REPLANS, replan, tier2_available
from vdagent_orchestrator.tests.test_dispatcher import REGISTRY, SCOPE, FakeSender, done, fail, run_of, step

EXPLAIN = (["EXPLAIN"], ["CHAT_ANSWER"])


def base(*extra: DraftStep) -> RunRecord:
    return run_of([step("B1", "data", "fetch_units", scope=SCOPE),
                   step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]),
                   step("B3", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]), *extra],
                  pinned=True, kinds=EXPLAIN)


def draft_json(steps: Sequence[DraftStep], drop: Sequence[str] = ()) -> str:
    return json.dumps(PlanDraft(steps=list(steps), drop=list(drop), rationale="sửa").model_dump(mode="json"))


def router(*script: Any) -> LlmRouter:
    return LlmRouter([FakeLLM(list(script))])


def cycle(run: RunRecord, sender: FakeSender, llm: LlmRouter | None, rounds: int = 3) -> RunRecord:
    """What one Orchestrator turn does: drive, replan, drive … until nothing moves."""
    async def go() -> RunRecord:
        current = run
        for _ in range(rounds):
            current = await drive(current, sender=sender, registry=REGISTRY, tier2_available=tier2_available(current, llm))
            current = await replan(current, router=llm, registry=REGISTRY)
        return await drive(current, sender=sender, registry=REGISTRY, tier2_available=tier2_available(current, llm))
    return asyncio.run(go())


def waves(sender: FakeSender) -> list[list[str]]:
    return [[o.step_id for o in wave] for wave in sender.waves]


def test_rpl1_trigger_classes_only() -> None:
    cases = {"INSIGHT_INVALID": True, "REQUIRED_ARTIFACT_MISSING": True, "SCOPE_VIOLATION": False, "INTERNAL_ERROR": False}
    for code, replans in cases.items():
        run = base()
        sender = FakeSender({"B1": done, "B2": done, "B3": lambda s, c=code: fail(s, c)})
        run = asyncio.run(drive(run, sender=sender, registry=REGISTRY, tier2_available=True))
        assert (run.pending == [{"kind": "REPLAN", "step_id": "B3"}]) is replans, code
    dq = run_of([step("B1", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"])], pinned=True)
    dq = asyncio.run(drive(dq, sender=FakeSender({"B1": lambda s: fail(s, "DQ_BLOCKING")}), registry=REGISTRY,
                           tier2_available=True))
    assert dq.pending == [] and dq.status == "failed"


def test_v16_replacement_rewires_waiters_old_not_rerun() -> None:
    run = base(step("B4", "chart", "draw_chart", ["B2", "B3"]), step("B5", "report", "draft_report", ["B2", "B3", "B4"]))
    sender = FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID"), "B6": done, "B4": done,
                         "B5": done})
    llm = router(draft_json([step("B6", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1", "T2"]
                                  ).model_copy(update={"replaces": "B3"})]))
    run = cycle(run, sender, llm)
    assert waves(sender) == [["B1", "B2"], ["B3"], ["B6"], ["B4"], ["B5"]]
    assert [r.artifact_id for r in sender.specs["B4"].input_refs] == ["art-B2", "art-B6"]
    assert run.steps["B6"].replaces == "B3" and run.steps["B6"].part_id == "B3" and run.replan_count == 1
    assert run.finished and run.status == "completed" and run.plan.version == 2


def test_v17_new_step_waits_old_running() -> None:
    run = base(step("B4", "chart", "draw_chart", ["B2", "B3"]))
    sender = FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID"), "B5": done, "B4": done,
                         "B6": done})
    new = [step("B5", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]).model_copy(update={"replaces": "B3"}),
           step("B6", "report", "draft_report", ["B2", "B4"])]
    run = cycle(run, sender, router(draft_json(new)))
    assert waves(sender) == [["B1", "B2"], ["B3"], ["B5"], ["B4"], ["B6"]]
    assert [r.artifact_id for r in sender.specs["B6"].input_refs] == ["art-B2", "art-B4"]


def test_rpl3_merge_into_queued() -> None:
    run = base(step("B4", "chart", "draw_chart", ["B2"]))
    fake = FakeLLM([draft_json([
        step("B5", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]).model_copy(update={"replaces": "B3"}),
        step("B6", "chart", "draw_chart", ["B2"]).model_copy(update={"replaces": "B4"})])])
    sender = FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID"),
                         "B4": lambda s: fail(s, "WRONG_RESULT"), "B5": done, "B6": done})
    run = cycle(run, sender, LlmRouter([fake]))
    assert len(fake.calls) == 1 and run.replan_count == 1
    items = json.loads(fake.calls[0]["messages"][1]["content"].split("<data>\n")[1].split("\n</data>")[0])["replan_items"]
    assert [i["step_id"] for i in items] == ["B3", "B4"]
    assert run.finished and run.status == "completed"


def test_max_two_replans_per_run() -> None:
    run = base()
    run.replan_count = MAX_REPLANS
    assert not tier2_available(run, router())
    run = cycle(run, FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "REQUIRED_ARTIFACT_MISSING")}), router())
    assert run.steps["B3"].status == "failed" and run.finished and run.status == "partial"  # reported directly


def test_one_replan_per_part() -> None:
    run = base()
    sender = FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "REQUIRED_ARTIFACT_MISSING"),
                         "B4": lambda s: fail(s, "REQUIRED_ARTIFACT_MISSING")})
    llm = router(draft_json([step("B4", "insight", "explain_slow_moving", ["B1", "B2"], tasks=["T1"]
                                  ).model_copy(update={"replaces": "B3"})]))
    run = cycle(run, sender, llm)
    assert run.replan_count == 1 and run.steps["B4"].replan_used  # the part used its replacement
    assert run.steps["B4"].status == "failed" and run.finished and run.status == "partial"


def test_v19_run_not_closed_while_replan_pending() -> None:
    run = base()
    run = asyncio.run(drive(run, sender=FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID")}),
                            registry=REGISTRY, tier2_available=True))
    assert not run.finished and run.steps["B3"].flags == ["awaiting_replan"]
    assert all(run.steps[s].status == "completed" for s in ("B1", "B2"))


def test_v23_extra_needs_low_confidence_or_drop() -> None:
    lookup = (["LOOKUP"], ["CHAT_ANSWER"])
    need = step("B1", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"], extra_needs=["giá thuê"])
    low = cycle(run_of([need], pinned=True, kinds=lookup),
                FakeSender({"B1": lambda s: done(s, warnings=["LOW_CONFIDENCE"], data_confidence="LOW")}), router())
    assert low.status == "completed" and low.warnings == [{"step_id": "B1", "code": "LOW_CONFIDENCE"}]
    assert low.steps["B1"].status == "completed"
    rewritten = step("B2", "data", "aggregate_metrics", scope=SCOPE, metrics=["avg_dom_unsold"]).model_copy(
        update={"replaces": "B1"})
    sender = FakeSender({"B1": lambda s: fail(s, "DATA_UNAVAILABLE"), "B2": done})
    dropped = cycle(run_of([need], pinned=True, kinds=lookup), sender, router(draft_json([rewritten])))
    assert "extra_needs" not in sender.specs["B2"].spec and dropped.status == "completed"
    kept = cycle(run_of([need], pinned=True, kinds=lookup),
                 FakeSender({"B1": lambda s: fail(s, "DATA_UNAVAILABLE"), "B2": lambda s: fail(s, "DATA_UNAVAILABLE")}),
                 router(draft_json([rewritten.model_copy(update={"spec": {**rewritten.spec, "extra_needs": ["giá thuê"]}})])))
    assert kept.finished and kept.status == "failed"


def test_v4_insight_own_code_classified() -> None:
    def insight_fails(spec: StepSpec) -> AgentReport:
        return fail(spec, "REQUIRED_ARTIFACT_MISSING")  # Insight could not get the context it asked Data for

    run = asyncio.run(drive(base(), sender=FakeSender({"B1": done, "B2": done, "B3": insight_fails}), registry=REGISTRY,
                            tier2_available=True))
    b3 = run.steps["B3"]
    assert b3.error_class is not None and b3.error_class.value == "SPEC_ISSUE" and b3.flags == ["awaiting_replan"]


def test_rpl7_abandoned_goes_tier3_or_direct() -> None:
    invalid = draft_json([step("B4", "insight", "explain_slow_moving", ["B1"], tasks=["T1"])])  # misses metric_table
    wrong = cycle(base(), FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "INSIGHT_INVALID")}),
                  router(invalid, invalid))
    assert wrong.pending == [{"kind": "DECISION", "step_id": "B3"}] and wrong.steps["B3"].flags == ["awaiting_decision"]
    assert not wrong.finished and any(e["event"] == "REPLAN_ABANDONED" for e in wrong.events)
    spec_issue = cycle(base(), FakeSender({"B1": done, "B2": done, "B3": lambda s: fail(s, "REQUIRED_ARTIFACT_MISSING")}),
                       router(LlmError(LlmErrorCode.TRANSIENT, "down")))
    assert spec_issue.steps["B3"].flags == [] and spec_issue.finished and spec_issue.status == "partial"
