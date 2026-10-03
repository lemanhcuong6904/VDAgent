"""WS5: the Orchestrator's code-enforced DAG — validation, planning, scheduling, parallelism, state and failures."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest

from vdagent_contracts.catalogs import load_catalog
from vdagent_contracts.reports import AgentReport, parse_agent_report, render_agent_report
from vdagent_orchestrator.dag import InputBinding, Plan, PlanError, PlanStep, validate_plan
from vdagent_orchestrator.answer import run_and_answer
from vdagent_orchestrator.planner import AnalysisRequest, build_plan, classify, parse_request
from vdagent_orchestrator.tests.dag_fakes import SEM, SNAP, FakeCtx, FakeTools, golden_handlers, report
from vdagent_sdk import AgentTimeoutError

QUESTION = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng và vẽ biểu đồ."
CATALOGS = {a: load_catalog(a) for a in ("data", "insight", "compare", "chart", "report")}


def golden_plan(run_id: str = "t_1") -> Plan:
    request = classify(QUESTION, snapshot_id=SNAP, semantic_config_version=SEM)
    assert request is not None
    return build_plan(request, run_id)


async def run(handlers: dict[str, Any], tools: FakeTools, plan: Plan | None = None, **kw: Any) -> tuple[Any, FakeCtx]:
    ctx = FakeCtx(QUESTION, handlers)
    outcome = await run_and_answer(ctx, tools, plan or golden_plan(), **kw)
    return outcome, ctx


# ---- catalogs -------------------------------------------------------------------------------------------------------


def test_catalogs_declare_the_implemented_operations() -> None:
    from vdagent_chart.stepspec import CHART_ERROR_CLASSES, OPERATIONS as CHART_OPS
    from vdagent_compare.stepspec import COMPARE_ERROR_CLASSES, OPERATIONS as COMPARE_OPS
    from vdagent_data.steps import DATA_ERROR_CLASSES
    from vdagent_insight.stepspec import INSIGHT_ERROR_CLASSES, OPERATIONS as INSIGHT_OPS

    expected = {"data": (("fetch_units", "aggregate_metrics"), DATA_ERROR_CLASSES),
                "insight": (INSIGHT_OPS, INSIGHT_ERROR_CLASSES), "compare": (COMPARE_OPS, COMPARE_ERROR_CLASSES),
                "chart": (CHART_OPS, CHART_ERROR_CLASSES)}
    for agent, (ops, errors) in expected.items():
        catalog = CATALOGS[agent]
        assert catalog.fixture is False
        assert sorted(o.operation for o in catalog.operations) == sorted(ops)
        for op in catalog.operations:
            assert op.error_codes == errors, f"{agent}.{op.operation} error codes out of sync"
    assert CATALOGS["data"].operation("fetch_units").produces == ["dataset", "metric", "dq"]
    assert CATALOGS["insight"].operation("explain_unit").requires == ["dataset", "metric", "dq"]
    assert CATALOGS["compare"].operation("compare_to_peers").produces == ["peer_definition", "comparison"]
    assert CATALOGS["chart"].operation("draw_chart").uses_if_present == ["dataset", "insight", "comparison", "peer_definition"]


# ---- planning + validation ------------------------------------------------------------------------------------------


def test_classify_and_golden_plan() -> None:
    request = classify(QUESTION, snapshot_id=SNAP, semantic_config_version=SEM)
    assert request == AnalysisRequest(QUESTION, "A12-08", frozenset({"explain", "compare", "chart"}), SNAP, SEM)
    plan = golden_plan()
    assert [(s.step_id, s.agent, s.operation, s.depends_on) for s in plan.steps] == [
        ("B1", "data", "fetch_units", ()), ("B2", "insight", "explain_unit", ("B1",)),
        ("B3", "compare", "compare_to_peers", ("B1",)), ("B4", "chart", "draw_chart", ("B1", "B2", "B3")),
    ]
    assert plan.steps[3].dependency_mode == "any"
    assert validate_plan(plan, CATALOGS) == [["B1"], ["B2", "B3"], ["B4"]]
    assert plan.plan_id == golden_plan().plan_id  # deterministic


def test_classify_needs_a_unit_code_and_does_not_guess() -> None:
    assert classify("doanh thu theo vùng năm 2025?", snapshot_id=SNAP, semantic_config_version=SEM) is None
    only = classify("Vì sao căn A12-08 bán chậm?", snapshot_id=SNAP, semantic_config_version=SEM)
    assert only is not None and only.wants == frozenset({"explain"})
    assert [s.step_id for s in build_plan(only, "t_1").steps] == ["B1", "B2"]


def test_structured_request_contract() -> None:
    req = parse_request({"contract": "AnalysisRequest@1", "question": QUESTION, "subject_unit_code": "A12-08",
                         "wants": ["explain", "compare", "chart"], "snapshot_id": SNAP, "semantic_config_version": SEM})
    assert req.wants == frozenset({"explain", "compare", "chart"})
    for bad in ({"question": QUESTION}, {"contract": "AnalysisRequest@1", "question": QUESTION, "subject_unit_code": "A12-08", "wants": ["explain"],
                 "snapshot_id": None, "semantic_config_version": SEM}):
        with pytest.raises(PlanError):
            parse_request(bad)
    report_req = parse_request({"contract": "AnalysisRequest@1", "question": REPORT_Q, "subject_unit_code": "A12-08",
                                "wants": ["report"], "snapshot_id": SNAP, "semantic_config_version": SEM})
    assert report_req.wants == frozenset({"report"})


def _plan(*steps: PlanStep, snapshot: str | None = SNAP) -> Plan:
    return Plan("pl_x", "t_1", snapshot, SEM, "q", steps)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("steps", "code"),
    [
        ((), "EMPTY_PLAN"),
        ((PlanStep("B1", "data", "fetch_units", {}), PlanStep("B1", "data", "fetch_units", {})), "DUPLICATE_STEP"),
        ((PlanStep("S1", "data", "fetch_units", {}),), "INVALID_STEP_ID"),
        ((PlanStep("B1", "report", "publish", {}),), "UNSUPPORTED_OPERATION"),  # WS6: report is a target, publish is not
        ((PlanStep("B1", "orchestrator", "fetch_units", {}),), "UNSUPPORTED_AGENT"),
        ((PlanStep("B1", "data", "drop_tables", {}),), "UNSUPPORTED_OPERATION"),
        ((PlanStep("B1", "data", "fetch_units", {}, ("B9",)),), "UNKNOWN_DEPENDENCY"),
        ((PlanStep("B1", "data", "fetch_units", {}, ("B2",)), PlanStep("B2", "insight", "explain_unit", {}, ("B1",))), "CYCLE"),
        ((PlanStep("B1", "data", "fetch_units", {}, ("B1",)),), "CYCLE"),
        ((PlanStep("B1", "data", "fetch_units", {}), PlanStep("B2", "insight", "explain_unit", {}, (), "all",
                                                           (InputBinding("B1", ("dataset",)),))), "INPUT_NOT_FROM_DEPENDENCY"),
    ],
)
def test_invalid_plans_are_rejected(steps: tuple[PlanStep, ...], code: str) -> None:
    with pytest.raises(PlanError) as exc:
        validate_plan(_plan(*steps), CATALOGS)
    assert exc.value.code == code


def test_plan_needs_one_snapshot_and_semantic() -> None:
    with pytest.raises(PlanError) as exc:
        validate_plan(_plan(PlanStep("B1", "data", "fetch_units", {}), snapshot=None), CATALOGS)
    assert exc.value.code == "SNAPSHOT_REQUIRED"
    with pytest.raises(PlanError) as exc:
        validate_plan(replace(golden_plan(), semantic_config_version=""), CATALOGS)
    assert exc.value.code == "SEMANTIC_VERSION_REQUIRED"


# ---- scheduling, parallelism, lineage -------------------------------------------------------------------------------


async def test_golden_dag_order_parallelism_and_identical_refs() -> None:
    tools, log = FakeTools(), []
    outcome, ctx = await run(golden_handlers(tools, barrier=asyncio.Barrier(2), log=log), tools)
    assert outcome.status == "partial"  # upstream limitations are carried, nothing failed
    assert all(s.status == "completed" for s in outcome.steps.values())
    assert log.index("data:end") < log.index("insight:start") and log.index("data:end") < log.index("compare:start")
    assert log.index("chart:start") > max(log.index("insight:end"), log.index("compare:end"))
    # B2 and B3 were dispatched in one assistant step and met at the barrier: they overlapped
    waves = [[c.id for c in calls] for _, calls in ctx.steps if calls]
    assert [len(w) for w in waves] == [1, 2, 1]
    sent = {s["step_id"]: s for _, s in ctx.sent}
    assert sent["B2"]["input_refs"] == sent["B3"]["input_refs"] == outcome.steps["B1"].output_refs
    assert all(r["content_hash"] for r in sent["B2"]["input_refs"])
    assert sent["B2"]["spec"]["analysis_scope"] == {"level": "UNIT", "project_ids": ["PRJ-X"], "unit_ids": ["U-PRJ-X-A12-08"]}
    assert {r["artifact_type"] for r in sent["B4"]["input_refs"]} == {"dataset", "insight", "peer_definition", "comparison"}
    assert [r for r in sent["B4"]["input_refs"] if r["artifact_type"] == "dataset"] == [
        r for r in outcome.steps["B1"].output_refs if r["artifact_type"] == "dataset"
    ]
    for step in ctx.sent:
        assert step[1]["snapshot_id"] == SNAP and step[1]["semantic_config_version"] == SEM
        assert step[1]["contract"] == "StepSpec@1" and step[1]["idempotency_key"] == f"{outcome.plan_id}:{step[1]['step_id']}"


async def test_run_state_is_persisted_per_step() -> None:
    tools = FakeTools()
    outcome, _ = await run(golden_handlers(tools), tools)
    states = [e for e in tools.arts.values() if e["artifact_type"] == "run_state"]
    assert len(states) >= 5 and len({e["artifact_id"] for e in states}) == 1  # one run_state, versioned
    last = max(states, key=lambda e: e["version"])
    p = last["payload"]
    assert p["plan_id"] == outcome.plan_id and p["status"] == "partial"
    assert [s["step_id"] for s in p["steps"]] == ["B1", "B2", "B3", "B4"]
    for s in p["steps"]:
        assert s["status"] == "completed" and s["started_at"] and s["finished_at"] and s["output_refs"]
    assert p["steps"][1]["input_refs"] == p["steps"][0]["output_refs"]
    assert "METRIC_UNAVAILABLE:discount_pct" in p["steps"][0]["limitations"]


async def test_answer_quotes_artifact_values_and_cites_ids() -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools), tools)
    text = ctx.answer
    for value in ("138", "61", "72.500.000", "64.500.000", "12,40"):
        assert value in text
    for ref in outcome.steps["B4"].output_refs + outcome.steps["B3"].output_refs:
        assert ref["artifact_id"] in text


async def test_repeated_invocation_does_not_rerun_completed_steps() -> None:
    tools, log = FakeTools(), []
    handlers = golden_handlers(tools, log=log)
    await run(handlers, tools)
    first = list(log)
    outcome, ctx = await run(handlers, tools)  # same task / plan again
    assert log == first and ctx.sent == []
    assert outcome.status == "partial" and all(s.reused for s in outcome.steps.values())


# ---- failures --------------------------------------------------------------------------------------------------------


async def test_data_failure_stops_everything() -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools, fail={"data"}), tools)
    assert outcome.status == "failed" and outcome.steps["B1"].error["code"] == "DATA_BROKEN"
    assert [outcome.steps[s].status for s in ("B2", "B3", "B4")] == ["skipped"] * 3
    assert [t for t, _ in ctx.sent] == ["data"]
    assert ctx.answer.startswith("Không hoàn thành")


@pytest.mark.parametrize(("broken", "kept"), [("insight", "comparison"), ("compare", "insight")])
async def test_one_analysis_failure_still_charts_the_other(broken: str, kept: str) -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools, fail={broken}), tools)
    assert outcome.status == "partial"
    chart_inputs = {r["artifact_type"] for t, s in ctx.sent if t == "chart" for r in s["input_refs"]}
    assert kept in chart_inputs and ({"insight"} if broken == "insight" else {"comparison", "peer_definition"}).isdisjoint(chart_inputs)
    assert outcome.steps["B4"].status == "completed"
    assert f"UPSTREAM_FAILED:{broken}" in outcome.steps["B4"].limitations


async def test_both_analysis_failures_skip_the_chart() -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools, fail={"insight", "compare"}), tools)
    assert outcome.status == "failed" and outcome.steps["B4"].status == "skipped"
    assert "chart" not in [t for t, _ in ctx.sent]


async def test_chart_failure_is_a_partial_answer() -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools, fail={"chart"}), tools)
    assert outcome.status == "partial" and outcome.steps["B4"].status == "failed"
    assert "biểu đồ" in ctx.answer.lower() and "138" in ctx.answer


async def test_malformed_report_and_rejected_call_fail_the_step() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)

    async def garbage(step: dict[str, Any]) -> str:
        return "ok, done!"

    async def rejected(step: dict[str, Any]) -> str:
        return "error: call depth limit reached; answer your caller with what you have"

    outcome, _ = await run({**handlers, "compare": garbage, "insight": rejected}, tools)
    assert outcome.steps["B3"].error["code"] == "MALFORMED_REPORT"
    assert outcome.steps["B2"].error["code"] == "CALL_REJECTED"
    assert outcome.steps["B4"].status == "skipped"


async def test_tampered_or_mismatched_refs_are_never_forwarded() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)

    async def bad_data(step: dict[str, Any]) -> str:
        env = tools.put({"artifact_type": "dataset", "schema_version": "re_dataset@1", "status": "VALID", "producer": {"agent": "data"},
                         "payload": {}, "snapshot_refs": ["SNAP-2026-09-29"]})
        return report(step, refs=[{**tools.ref(env)}])

    outcome, ctx = await run({**handlers, "data": bad_data}, tools)
    assert outcome.steps["B1"].error["code"] == "REF_SNAPSHOT_MISMATCH" and [t for t, _ in ctx.sent] == ["data"]

    async def tampered(step: dict[str, Any]) -> str:
        text = await handlers["data"](step)
        return text.replace('"content_hash": "', '"content_hash": "0', 1)

    tools2 = FakeTools()
    handlers2 = golden_handlers(tools2)
    outcome, ctx = await run({**handlers2, "data": tampered}, tools2)
    assert outcome.steps["B1"].status == "failed" and outcome.steps["B1"].error["code"] in ("REF_HASH_MISMATCH", "MALFORMED_REPORT")
    assert [t for t, _ in ctx.sent] == ["data"]


async def test_unexpected_artifact_type_is_rejected() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)

    async def wrong(step: dict[str, Any]) -> str:
        env = tools.put({"artifact_type": "chart_spec", "schema_version": "chart_spec@1", "status": "VALID", "producer": {"agent": "x"}, "payload": {}})
        return report(step, refs=[tools.ref(env)])

    outcome, _ = await run({**handlers, "compare": wrong}, tools)
    assert outcome.steps["B3"].error["code"] == "REF_TYPE_UNEXPECTED"


async def test_timeout_cancels_pending_calls_without_orphans() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)
    hang = asyncio.Event()

    async def stuck(step: dict[str, Any]) -> str:
        await hang.wait()
        return ""

    before = set(asyncio.all_tasks())
    with pytest.raises(AgentTimeoutError):
        await run({**handlers, "insight": stuck, "compare": stuck}, tools, timeout_s=0.2)
    await asyncio.sleep(0)
    assert set(asyncio.all_tasks()) - before - {asyncio.current_task()} == set()
    last = max((e for e in tools.arts.values() if e["artifact_type"] == "run_state"), key=lambda e: e["version"])
    assert last["payload"]["status"] == "timed_out"


async def test_unknown_agent_reply_is_a_failed_step() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)
    del handlers["chart"]
    outcome, _ = await run(handlers, tools)
    assert outcome.steps["B4"].error["code"] == "CALL_REJECTED"


@pytest.mark.parametrize("wants", [[{}], [[]], ["explain", {}]])
def test_invalid_request_wants_is_a_plan_error(wants: list[Any]) -> None:
    with pytest.raises(PlanError) as exc:
        parse_request({"contract": "AnalysisRequest@1", "question": QUESTION, "subject_unit_code": "A12-08",
                       "wants": wants, "snapshot_id": SNAP, "semantic_config_version": SEM})
    assert exc.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize(("field", "value"), [
    ("run_id", "another_run"), ("snapshot_id", "another_snapshot"), ("semantic_config_version", "another_semantic"),
])
async def test_report_must_match_the_run_pins(field: str, value: str) -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)

    async def wrong_report(step: dict[str, Any]) -> str:
        result = parse_agent_report(await handlers["data"](step))
        assert isinstance(result, AgentReport)
        return render_agent_report("wrong metadata", result.model_copy(update={field: value}))

    outcome, ctx = await run({**handlers, "data": wrong_report}, tools)
    assert outcome.steps["B1"].error["code"] == "MALFORMED_REPORT"
    assert [agent for agent, _ in ctx.sent] == ["data"]


@pytest.mark.parametrize(("field", "value", "code"), [
    ("artifact_type", "comparison", "REF_TYPE_UNEXPECTED"),
    ("status", "INVALID", "REF_STATUS_INVALID"),
    ("status", "DRAFT", "REF_STATUS_INVALID"),
])
async def test_stored_artifact_must_be_usable_and_match_declared_type(field: str, value: str, code: str) -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)

    async def wrong_artifact(step: dict[str, Any]) -> str:
        result = parse_agent_report(await handlers["chart"](step))
        assert isinstance(result, AgentReport)
        for ref in result.artifact_refs:
            tools.arts[(ref.artifact_id, ref.version)][field] = value
        return render_agent_report("wrong artifact", result)

    # Chart is terminal here: no downstream resolver can mask a missing executor check.
    outcome, _ = await run({**handlers, "chart": wrong_artifact}, tools)
    assert outcome.steps["B4"].status == "failed"
    assert outcome.steps["B4"].error["code"] == code


async def test_artifact_partial_and_limitations_reach_the_answer() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)

    async def partial_chart(step: dict[str, Any]) -> str:
        result = parse_agent_report(await handlers["chart"](step))
        assert isinstance(result, AgentReport)
        for ref in result.artifact_refs:
            tools.arts[(ref.artifact_id, ref.version)].update(status="PARTIAL", limitations=["CHART_DATA_MISSING"])
        return render_agent_report("completed", result.model_copy(update={"partial": False, "warnings": []}))

    outcome, ctx = await run({**handlers, "chart": partial_chart}, tools)
    assert outcome.steps["B4"].partial is True
    assert "CHART_DATA_MISSING" in ctx.answer


def test_request_json_round_trip() -> None:
    plan = golden_plan()
    assert json.loads(json.dumps(plan.to_json()))["steps"][3]["dependency_mode"] == "any"


# ---- WS6: Report Mode (B5) ---------------------------------------------------------------------------------------------

REPORT_Q = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."


def report_plan() -> Plan:
    request = classify(REPORT_Q, snapshot_id=SNAP, semantic_config_version=SEM)
    assert request is not None and "report" in request.wants
    return build_plan(request, "t_1")


def test_report_catalog_matches_the_implementation() -> None:
    from vdagent_report.stepspec import OPERATIONS as REPORT_OPS
    from vdagent_report.stepspec import REPORT_ERROR_CLASSES

    catalog = load_catalog("report")
    assert catalog.fixture is False and [o.operation for o in catalog.operations] == list(REPORT_OPS)
    op = catalog.operation("draft_report")
    assert op.produces == ["report"] and op.error_codes == REPORT_ERROR_CLASSES
    assert op.uses_if_present == ["insight", "comparison", "peer_definition", "chart_spec"]


def test_report_mode_plans_b5_after_the_chart_and_chat_mode_does_not() -> None:
    plan = report_plan()
    assert [(s.step_id, s.agent, s.operation) for s in plan.steps][-1] == ("B5", "report", "draft_report")
    assert plan.steps[-1].depends_on == ("B2", "B3", "B4") and plan.steps[-1].dependency_mode == "any"
    assert validate_plan(plan, CATALOGS) == [["B1"], ["B2", "B3"], ["B4"], ["B5"]]
    assert "report" not in {s.agent for s in golden_plan().steps}  # Chat Mode stops after B4
    only = classify("Xuất báo cáo cho căn A12-08", snapshot_id=SNAP, semantic_config_version=SEM)
    assert only is not None and only.wants == frozenset({"explain", "compare", "chart", "report"})


async def test_b5_receives_the_exact_verified_refs_and_is_recorded() -> None:
    tools, log = FakeTools(), []
    outcome, ctx = await run(golden_handlers(tools, barrier=asyncio.Barrier(2), log=log), tools, report_plan())
    assert outcome.steps["B5"].status == "completed" and log[-2:] == ["report:start", "report:end"]
    sent = {s["step_id"]: s for _, s in ctx.sent}
    expected = [*outcome.steps["B2"].output_refs, *outcome.steps["B3"].output_refs, *outcome.steps["B4"].output_refs]
    assert sent["B5"]["input_refs"] == expected
    state = max((e for e in tools.arts.values() if e["artifact_type"] == "run_state"), key=lambda e: e["version"])
    assert [s["step_id"] for s in state["payload"]["steps"]][-1] == "B5"
    assert outcome.steps["B5"].output_refs[0]["artifact_type"] == "report"
    assert outcome.steps["B5"].output_refs[0]["artifact_id"] in ctx.answer


async def test_report_failure_keeps_the_analysis() -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools, fail={"report"}), tools, report_plan())
    assert outcome.status == "partial" and outcome.steps["B5"].status == "failed"
    assert all(outcome.steps[s].status == "completed" for s in ("B1", "B2", "B3", "B4"))
    assert "báo cáo" in ctx.answer.lower() and "REPORT_BROKEN" in ctx.answer and "138" in ctx.answer


async def test_report_runs_on_what_is_left_and_is_skipped_when_nothing_is() -> None:
    tools = FakeTools()
    outcome, ctx = await run(golden_handlers(tools, fail={"chart"}), tools, report_plan())
    assert outcome.steps["B5"].status == "completed" and "UPSTREAM_FAILED:chart" in outcome.steps["B5"].limitations
    tools2 = FakeTools()
    outcome, ctx = await run(golden_handlers(tools2, fail={"insight", "compare"}), tools2, report_plan())
    assert outcome.steps["B5"].status == "skipped" and "report" not in [t for t, _ in ctx.sent]


async def test_repeated_report_mode_does_not_duplicate_the_report() -> None:
    tools, log = FakeTools(), []
    handlers = golden_handlers(tools, log=log)
    await run(handlers, tools, report_plan())
    reports = [e for e in tools.arts.values() if e["artifact_type"] == "report"]
    outcome, ctx = await run(handlers, tools, report_plan())
    assert ctx.sent == [] and [e for e in tools.arts.values() if e["artifact_type"] == "report"] == reports
    assert outcome.steps["B5"].reused


async def test_report_timeout_is_a_timed_out_run() -> None:
    tools = FakeTools()
    handlers = golden_handlers(tools)
    hang = asyncio.Event()

    async def stuck(step: dict[str, Any]) -> str:
        await hang.wait()
        return ""

    with pytest.raises(AgentTimeoutError):
        await run({**handlers, "report": stuck}, tools, report_plan(), timeout_s=0.5)
    last = max((e for e in tools.arts.values() if e["artifact_type"] == "run_state"), key=lambda e: e["version"])
    assert last["payload"]["status"] == "timed_out"
    assert {s["step_id"]: s["status"] for s in last["payload"]["steps"]}["B4"] == "completed"


# ---- WS7 F-03: the run outcome reaches the Backend ------------------------------------------------------------------


@pytest.mark.parametrize(("fail", "outcome"), [(set(), "partial"), ({"data"}, "failed"), ({"insight", "compare"}, "failed"),
                                                ({"chart"}, "partial")])
async def test_run_outcome_is_reported(fail: set[str], outcome: str) -> None:
    tools = FakeTools()
    _, ctx = await run(golden_handlers(tools, fail=fail), tools)
    assert ctx.outcome == outcome

