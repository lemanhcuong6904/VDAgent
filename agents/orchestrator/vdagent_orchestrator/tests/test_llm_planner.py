"""ORCH_LLM=on: the LLM proposes intent + plan structure; code validates it and the existing DAG executor runs it."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from vdagent_orchestrator import agent as agent_module
from vdagent_orchestrator.agent import OrchestratorAgent, build_agent
from vdagent_orchestrator.dag import PlanError
from vdagent_orchestrator.llm import AssistantMessage, LLMTimeoutError
from vdagent_orchestrator.llm_planner import plan_with_llm
from vdagent_orchestrator.tests.dag_fakes import SEM, SNAP, FakeCtx, FakeTools, golden_handlers

QUESTION = "Why is unit A12-08 selling slowly? Compare it with similar units, create charts, and generate a report."
VI_QUESTION = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."

GOLDEN = {
    "intent": {"in_scope": True, "subject_unit_code": "A12-08", "wants": ["explain", "compare", "chart", "report"]},
    "steps": [
        {"step_id": "B1", "agent": "data", "operation": "fetch_units", "depends_on": []},
        {"step_id": "B2", "agent": "insight", "operation": "explain_unit", "depends_on": ["B1"]},
        {"step_id": "B3", "agent": "compare", "operation": "compare_to_peers", "depends_on": ["B1"]},
        {"step_id": "B4", "agent": "chart", "operation": "draw_chart", "depends_on": ["B2", "B3"]},
        {"step_id": "B5", "agent": "report", "operation": "draft_report", "depends_on": ["B2", "B3", "B4"]},
    ],
}


class ScriptedLLM:
    model = "fake-planner"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]], str]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str) -> AssistantMessage:
        self.calls.append((messages, tools, tool_choice))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return AssistantMessage(content=reply)


def test_prompt_names_agent_and_operation_as_separate_fields() -> None:
    from vdagent_contracts.catalogs import load_catalog
    from vdagent_orchestrator.llm_planner import system_prompt

    prompt = system_prompt({a: load_catalog(a) for a in ("data", "insight", "compare", "chart", "report")})
    assert '"agent": "data", "operation": "fetch_units"' in prompt and "data.fetch_units" not in prompt


def test_prompt_only_offers_operations_the_unit_workflow_can_compile() -> None:
    from vdagent_contracts.catalogs import load_catalog
    from vdagent_orchestrator.llm_planner import system_prompt

    prompt = system_prompt({a: load_catalog(a) for a in ("data", "insight", "compare", "chart", "report")})
    assert "aggregate_metrics" not in prompt


def _with(**changes: Any) -> str:
    plan = json.loads(json.dumps(GOLDEN))
    for path, value in changes.items():
        step, key = path.split("__")
        plan["steps"][int(step[1:]) - 1][key] = value
    return json.dumps(plan)


async def _plan(reply: str, question: str = QUESTION) -> Any:
    return await plan_with_llm(ScriptedLLM(reply), question, run_id="t_1", snapshot_id=SNAP, semantic_config_version=SEM)


# ---- 1. a valid LLM plan becomes a validated DAG ----------------------------------------------------------------------


async def test_valid_llm_plan_is_compiled_with_code_owned_specs_and_pins() -> None:
    llm = ScriptedLLM("```json\n" + json.dumps(GOLDEN) + "\n```")
    plan, waves = await plan_with_llm(llm, QUESTION, run_id="t_1", snapshot_id=SNAP, semantic_config_version=SEM)
    assert waves == [["B1"], ["B2", "B3"], ["B4"], ["B5"]]
    assert [(s.step_id, s.agent, s.operation, s.depends_on) for s in plan.steps] == [
        ("B1", "data", "fetch_units", ()), ("B2", "insight", "explain_unit", ("B1",)),
        ("B3", "compare", "compare_to_peers", ("B1",)), ("B4", "chart", "draw_chart", ("B1", "B2", "B3")),
        ("B5", "report", "draft_report", ("B2", "B3", "B4"))]
    assert (plan.snapshot_id, plan.semantic_config_version) == (SNAP, SEM)  # pinned by code, never by the LLM
    assert plan.steps[0].spec == {"subject_unit_code": "A12-08", "population": "peer_candidates"}
    assert plan.provenance["planner"] == "llm" and plan.provenance["model"] == "fake-planner"
    assert plan.provenance["llm_plan"] == GOLDEN and plan.provenance["llm_calls"] == 1
    [(messages, tools, choice)] = llm.calls
    assert tools == [] and choice == "none"  # the LLM gets no tools: it cannot orchestrate anything itself
    assert QUESTION in messages[-1]["content"] and "fetch_units" in messages[0]["content"]  # catalog in the prompt


async def test_llm_plan_runs_on_the_existing_executor_with_b2_b3_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    tools, log = FakeTools(), []
    ctx = FakeCtx(VI_QUESTION, golden_handlers(tools, barrier=asyncio.Barrier(2), log=log))
    llm = ScriptedLLM(json.dumps(GOLDEN))
    await _agent(llm, tools, monkeypatch).invoke(ctx)
    assert len(llm.calls) == 1 and ctx.outcome == "partial"
    assert [len(calls) for _, calls in ctx.steps if calls] == [1, 2, 1, 1]  # B1 | B2 ∥ B3 (barrier met) | B4 | B5
    assert log[-2:] == ["report:start", "report:end"]
    sent = {s["step_id"]: s for _, s in ctx.sent}
    assert sent["B2"]["input_refs"] == sent["B3"]["input_refs"]
    state = max((e for e in tools.arts.values() if e["artifact_type"] == "run_state"), key=lambda e: e["version"])
    assert state["payload"]["plan"]["provenance"]["planner"] == "llm"
    assert state["payload"]["waves"] == [["B1"], ["B2", "B3"], ["B4"], ["B5"]]


# ---- 2–6. unsafe LLM output is rejected before anything runs ---------------------------------------------------------


@pytest.mark.parametrize(("reply", "code"), [
    ("Sure! Here is the plan: B1 data, B2 insight…", "LLM_PLAN_MALFORMED"),
    ("{\"intent\": {}, \"steps\": [", "LLM_PLAN_MALFORMED"),
    (json.dumps({"steps": []}), "LLM_PLAN_MALFORMED"),
    (_with(B2__agent="pricing"), "UNSUPPORTED_AGENT"),
    (_with(B2__agent="orchestrator"), "UNSUPPORTED_AGENT"),
    (_with(B3__operation="compare_everything"), "UNSUPPORTED_OPERATION"),
    (_with(B1__operation="aggregate_metrics"), "UNSUPPORTED_OPERATION"),
    (_with(B1__agent="data.fetch_units", B1__operation="data.fetch_units"), "UNSUPPORTED_AGENT"),  # seen live: no guessing
    (_with(B1__depends_on=["B4"]), "CYCLE"),
    (_with(B4__depends_on=["B2", "B9"]), "UNKNOWN_DEPENDENCY"),
    (_with(B2__depends_on=[]), "LLM_PLAN_INVALID_DEPENDENCY"),
    (_with(B4__depends_on=["B1"]), "LLM_PLAN_INVALID_DEPENDENCY"),
    (_with(B4__depends_on=["B2"]), "LLM_PLAN_INVALID_DEPENDENCY"),
    (_with(B5__depends_on=["B2", "B3"]), "LLM_PLAN_INVALID_DEPENDENCY"),
    (_with(B5__depends_on=["B2", "B4"]), "LLM_PLAN_INVALID_DEPENDENCY"),
    (_with(B2__spec={"tasks": ["T9"]}), "LLM_PLAN_MALFORMED"),  # the LLM may not write specs
    (json.dumps({**GOLDEN, "steps": GOLDEN["steps"][:4]}), "LLM_PLAN_MISSING_STEP"),  # report asked, no report step
    (json.dumps({**GOLDEN, "steps": GOLDEN["steps"][1:]}), "LLM_PLAN_MISSING_STEP"),  # no data step
    (json.dumps({**GOLDEN, "intent": {**GOLDEN["intent"], "subject_unit_code": "B15-02"}}), "LLM_PLAN_UNGROUNDED"),
    (json.dumps({**GOLDEN, "snapshot_id": "latest"}), "LLM_PLAN_MALFORMED"),  # pins are code's, not the LLM's
    (json.dumps({**GOLDEN, "intent": {**GOLDEN["intent"], "in_scope": "true"}}), "LLM_PLAN_MALFORMED"),
    (json.dumps({**GOLDEN, "intent": {**GOLDEN["intent"], "wants": []}}), "LLM_PLAN_MALFORMED"),
    (json.dumps({**GOLDEN, "intent": {**GOLDEN["intent"], "wants": ["explain"]}}), "LLM_PLAN_UNEXPECTED_STEP"),
])
async def test_unsafe_llm_output_is_rejected(reply: str, code: str) -> None:
    with pytest.raises(PlanError) as err:
        await _plan(reply)
    assert err.value.code == code


async def test_llm_cannot_choose_one_of_several_units_without_clarification() -> None:
    with pytest.raises(PlanError) as err:
        await _plan(json.dumps(GOLDEN), question=QUESTION + " Also consider B15-02.")
    assert err.value.code == "LLM_PLAN_UNGROUNDED"


@pytest.mark.parametrize("reply", ["not json", _with(B2__agent="pricing"), _with(B1__depends_on=["B4"])])
async def test_rejected_llm_plan_fails_the_run_without_calling_any_agent(reply: str, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = FakeTools()
    ctx = FakeCtx(QUESTION, golden_handlers(tools))
    await _agent(ScriptedLLM(reply), tools, monkeypatch).invoke(ctx)
    assert ctx.sent == [] and ctx.outcome == "failed"
    [(text, calls)] = ctx.steps
    assert text.startswith("Không hoàn thành: ") and calls == []


async def test_llm_unavailable_is_a_safe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = FakeTools()
    ctx = FakeCtx(QUESTION, golden_handlers(tools))
    await _agent(ScriptedLLM(LLMTimeoutError("slow")), tools, monkeypatch).invoke(ctx)
    assert ctx.sent == [] and ctx.outcome == "failed" and "LLM_PLAN_UNAVAILABLE" in ctx.steps[0][0]


async def test_out_of_scope_question_is_answered_without_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = FakeTools()
    ctx = FakeCtx("Soạn giúp tôi một email chúc mừng", golden_handlers(tools))
    reply = json.dumps({"intent": {"in_scope": False, "subject_unit_code": None, "wants": []}, "steps": []})
    await _agent(ScriptedLLM(reply), tools, monkeypatch).invoke(ctx)
    assert ctx.sent == [] and ctx.outcome is None and len(ctx.steps) == 1


async def test_missing_snapshot_pin_is_refused() -> None:
    with pytest.raises(PlanError) as err:
        await plan_with_llm(ScriptedLLM(json.dumps(GOLDEN)), QUESTION, run_id="t_1", snapshot_id=None, semantic_config_version=SEM)
    assert err.value.code == "SNAPSHOT_REQUIRED"


# ---- 7. modes -------------------------------------------------------------------------------------------------------


def test_llm_on_never_takes_the_legacy_loop_unless_explicitly_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://llm.test", "LLM_MODEL": "m"}
    on = build_agent(keys)
    assert isinstance(on, OrchestratorAgent) and on.has_llm and not on.legacy_loop
    legacy = build_agent({**keys, "ORCH_LEGACY_LOOP": "on"})
    assert isinstance(legacy, OrchestratorAgent) and legacy.legacy_loop
    off = build_agent({"ORCH_LLM": "off"})
    assert isinstance(off, OrchestratorAgent) and not off.has_llm and not off.legacy_loop


async def test_legacy_loop_only_behind_its_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def legacy(self: Any, ctx: Any) -> None:
        called.append("legacy")

    monkeypatch.setattr(agent_module.LiteLLMAgent, "invoke", legacy)
    tools = FakeTools()
    llm = ScriptedLLM()  # no reply scripted: the planner must not be asked
    orch = OrchestratorAgent(llm=llm, system_prompt="s", compact_prompt="c", snapshot_id=SNAP, semantic_config_version=SEM,
                             legacy_loop=True)
    await orch.invoke(FakeCtx(QUESTION, golden_handlers(tools)))
    assert called == ["legacy"] and llm.calls == []


async def test_llm_off_still_uses_the_deterministic_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = FakeTools()
    ctx = FakeCtx(VI_QUESTION, golden_handlers(tools, barrier=asyncio.Barrier(2)))
    await _agent(None, tools, monkeypatch).invoke(ctx)
    state = max((e for e in tools.arts.values() if e["artifact_type"] == "run_state"), key=lambda e: e["version"])
    assert "provenance" not in state["payload"]["plan"]  # run_state unchanged for the deterministic path
    assert state["payload"]["waves"] == [["B1"], ["B2", "B3"], ["B4"], ["B5"]]


def _agent(llm: ScriptedLLM | None, tools: FakeTools, monkeypatch: pytest.MonkeyPatch) -> OrchestratorAgent:
    @asynccontextmanager
    async def session(url: str, token: str) -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(agent_module, "JsonTools", lambda _mcp: tools)
    return OrchestratorAgent(llm=llm, mcp_session_factory=session, system_prompt="s", compact_prompt="c",  # pyright: ignore[reportArgumentType]
                             snapshot_id=SNAP, semantic_config_version=SEM)


# ---- chart/report need the analyses they draw from (same rule as the deterministic planner) ---------------------------

def _plan_of(wants: list[str], agents: list[str]) -> str:
    deps = {"data": [], "insight": ["B1"], "compare": ["B1"]}
    steps, ids = [], {}
    for n, agent in enumerate(agents, 1):
        sid = f"B{n}"
        ids[agent] = sid
        if agent == "chart":
            dep = [ids[a] for a in ("insight", "compare") if a in ids]
        elif agent == "report":
            dep = [ids[a] for a in ("insight", "compare", "chart") if a in ids]
        else:
            dep = deps[agent]
        steps.append({"step_id": sid, "agent": agent, "operation": {"data": "fetch_units", "insight": "explain_unit",
                      "compare": "compare_to_peers", "chart": "draw_chart", "report": "draft_report"}[agent], "depends_on": dep})
    return json.dumps({"intent": {"in_scope": True, "subject_unit_code": "A12-08", "wants": wants}, "steps": steps})


HC3 = "Phân tích căn A12-08 và cho tôi các biểu đồ quan trọng."


@pytest.mark.parametrize(("wants", "agents"), [
    (["chart"], ["data", "insight", "chart"]),            # seen live for HC3: comparative charts impossible
    (["chart"], ["data", "compare", "chart"]),
    (["report"], ["data", "insight", "compare", "report"]),  # a report embeds the charts
])
async def test_charts_or_report_without_named_analysis_need_the_full_set(wants: list[str], agents: list[str]) -> None:
    with pytest.raises(PlanError) as err:
        await _plan(_plan_of(wants, agents), HC3)
    assert err.value.code == "LLM_PLAN_MISSING_STEP"


async def test_hc3_full_visual_plan_is_accepted() -> None:
    plan, waves = await _plan(_plan_of(["chart"], ["data", "insight", "compare", "chart"]), HC3)
    assert waves == [["B1"], ["B2", "B3"], ["B4"]]


async def test_explicit_single_analysis_with_chart_stays_allowed() -> None:
    _, waves = await _plan(_plan_of(["compare", "chart"], ["data", "compare", "chart"]), "So sánh căn A12-08 và vẽ biểu đồ")
    assert waves == [["B1"], ["B2"], ["B3"]]


def test_prompt_states_the_chart_and_report_rule() -> None:
    from vdagent_contracts.catalogs import load_catalog
    from vdagent_orchestrator.llm_planner import system_prompt

    prompt = system_prompt({a: load_catalog(a) for a in ("data", "insight", "compare", "chart", "report")})
    assert "without naming an analysis" in prompt and "a report needs the chart step" in prompt


def test_startup_log_states_the_planner_mode_without_secrets(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.INFO)
    build_agent({"OPENAI_API_KEY": "sk-secret-value", "OPENAI_BASE_URL": "http://llm.test", "LLM_MODEL": "m1",
                 "ORCH_LLM": "on", "ORCH_SNAPSHOT_ID": SNAP, "ORCH_SEMANTIC_VERSION": SEM})
    build_agent({"ORCH_LLM": "off"})
    text = caplog.text
    assert f"orchestrator: LLM planner on (model m1), snapshot {SNAP}, semantic {SEM}" in text
    assert "orchestrator: deterministic planner (ORCH_LLM=off)" in text and "sk-secret" not in text
