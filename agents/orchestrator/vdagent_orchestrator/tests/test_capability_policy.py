"""Intent → capability policy → canonical DAG: the LLM proposes, code decides.

Each agent is `required` (a requested output needs it), `optional` (allowed in a proposal because a requested output
can use it, but not needed: normalized away) or `forbidden`. A proposal is valid when required ⊆ proposed ⊆ allowed and
it is a valid DAG; the DAG that runs is always compiled by code from the required set, so it does not depend on which
optional steps the LLM happened to add.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from vdagent_orchestrator.dag import PlanError
from vdagent_orchestrator.llm_planner import plan_with_llm
from vdagent_orchestrator.planner import build_plan, capability_policy, classify
from vdagent_orchestrator.tests.dag_fakes import SEM, SNAP
from vdagent_orchestrator.tests.test_llm_planner import ScriptedLLM

OPS = {"data": "fetch_units", "insight": "explain_unit", "compare": "compare_to_peers", "chart": "draw_chart",
       "report": "draft_report"}


def proposal(wants: list[str], agents: list[str], code: str = "A12-08") -> str:
    ids: dict[str, str] = {}
    steps = []
    for n, agent in enumerate(agents, 1):
        ids[agent] = f"B{n}"
        deps = {"data": [], "insight": [ids.get("data")], "compare": [ids.get("data")],
                "chart": [ids[a] for a in ("insight", "compare") if a in ids],
                "report": [ids[a] for a in ("insight", "compare", "chart") if a in ids]}.get(agent, [ids.get("data")])
        steps.append({"step_id": f"B{n}", "agent": agent, "operation": OPS.get(agent, "fetch_units"), "depends_on": deps})
    return json.dumps({"intent": {"in_scope": True, "subject_unit_code": code, "wants": wants}, "steps": steps})


async def plan(reply: str, question: str) -> Any:
    return await plan_with_llm(ScriptedLLM(reply), question, run_id="t_1", snapshot_id=SNAP, semantic_config_version=SEM)


def shape(p: Any) -> list[tuple[str, str, tuple[str, ...]]]:
    return [(s.step_id, s.agent, s.depends_on) for s in p.steps]


def test_policy_states_required_optional_and_forbidden_per_capability() -> None:
    assert capability_policy({"explain"}) == {"data": "required", "insight": "required", "compare": "forbidden",
                                              "chart": "forbidden", "report": "forbidden"}
    assert capability_policy({"explain", "chart"}) == {"data": "required", "insight": "required", "compare": "optional",
                                                       "chart": "required", "report": "forbidden"}
    assert capability_policy({"compare", "chart"})["insight"] == "optional"
    assert capability_policy({"explain", "compare", "chart", "report"}) == dict.fromkeys(OPS, "required")
    assert capability_policy({"report"}) == dict.fromkeys(OPS, "required")  # a report embeds charts of both analyses


async def test_p1_why_is_data_and_insight() -> None:
    p, waves = await plan(proposal(["explain"], ["data", "insight"]), "Vì sao căn A12-08 bán chậm?")
    assert shape(p) == [("B1", "data", ()), ("B2", "insight", ("B1",))] and waves == [["B1"], ["B2"]]
    assert p.steps[0].spec["population"] == "subject"


@pytest.mark.parametrize("agents", [["data", "insight", "compare", "chart"], ["data", "insight", "chart"]])
async def test_p2_explain_and_chart_succeeds_whether_or_not_the_llm_adds_compare(agents: list[str]) -> None:
    p, waves = await plan(proposal(["explain", "chart"], agents), "Vì sao căn A12-08 bán chậm? Vẽ biểu đồ.")
    assert shape(p) == [("B1", "data", ()), ("B2", "insight", ("B1",)), ("B3", "chart", ("B2",))]
    assert waves == [["B1"], ["B2"], ["B3"]]
    assert p.provenance["normalized"] == {"dropped_optional": ["compare"] if "compare" in agents else []}


async def test_p2_the_canonical_dag_does_not_depend_on_the_optional_proposal() -> None:
    q = "Vì sao căn A12-08 bán chậm? Vẽ biểu đồ."
    with_compare, _ = await plan(proposal(["explain", "chart"], ["data", "insight", "compare", "chart"]), q)
    without, _ = await plan(proposal(["explain", "chart"], ["data", "insight", "chart"]), q)
    assert (with_compare.plan_id, shape(with_compare)) == (without.plan_id, shape(without))


async def test_p3_compare_is_data_and_compare() -> None:
    p, _ = await plan(proposal(["compare"], ["data", "compare"]), "So sánh căn A12-08 với các căn tương đồng.")
    assert shape(p) == [("B1", "data", ()), ("B2", "compare", ("B1",))]
    assert p.steps[0].spec["population"] == "peer_candidates"


async def test_p4_explain_compare_chart_runs_both_analyses_in_parallel() -> None:
    p, waves = await plan(proposal(["explain", "compare", "chart"], ["data", "insight", "compare", "chart"]),
                          "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng và vẽ biểu đồ.")
    assert waves == [["B1"], ["B2", "B3"], ["B4"]] and p.steps[3].depends_on == ("B2", "B3")


async def test_p5_report_comes_after_the_analyses_and_the_chart() -> None:
    p, waves = await plan(proposal(["explain", "compare", "chart", "report"], ["data", "insight", "compare", "chart", "report"]),
                          "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.")
    assert waves == [["B1"], ["B2", "B3"], ["B4"], ["B5"]] and p.steps[4].depends_on == ("B2", "B3", "B4")


@pytest.mark.parametrize(("wants", "agents", "code"), [
    (["explain"], ["data", "insight", "report"], "LLM_PLAN_UNEXPECTED_STEP"),  # report not asked for: forbidden
    (["explain"], ["data", "insight", "chart"], "LLM_PLAN_UNEXPECTED_STEP"),  # charts not asked for: forbidden
    (["explain"], ["data", "insight", "compare"], "LLM_PLAN_UNEXPECTED_STEP"),  # compare without a chart: no reason
    (["explain", "chart"], ["data", "insight", "pricing", "chart"], "UNSUPPORTED_AGENT"),  # unknown agent
    (["explain", "chart"], ["data", "compare", "chart"], "LLM_PLAN_MISSING_STEP"),  # required insight missing
])
async def test_p6_steps_outside_the_policy_are_rejected_precisely(wants: list[str], agents: list[str], code: str) -> None:
    with pytest.raises(PlanError) as err:
        await plan(proposal(wants, agents), "Vì sao căn A12-08 bán chậm? Vẽ biểu đồ.")
    assert err.value.code == code


async def test_p6_an_optional_step_must_still_sit_correctly_in_the_dag() -> None:
    bad = json.loads(proposal(["explain", "chart"], ["data", "insight", "compare", "chart"]))
    bad["steps"][3]["depends_on"] = ["B2"]  # chart ignores the compare step it was given
    with pytest.raises(PlanError) as err:
        await plan(json.dumps(bad), "Vì sao căn A12-08 bán chậm? Vẽ biểu đồ.")
    assert err.value.code == "LLM_PLAN_INVALID_DEPENDENCY"


@pytest.mark.parametrize("question", [
    "Vì sao căn A12-08 bán chậm? Vẽ biểu đồ.",
    "Tại sao căn A12-08 bán chậm, vẽ giúp tôi biểu đồ",
    "Căn A12-08 bán chậm vì lý do gì? Cho tôi đồ thị.",
    "Nguyên nhân căn A12-08 bán chậm và biểu đồ minh họa",
])
def test_p7_equivalent_phrasings_give_the_same_capabilities_and_dag(question: str) -> None:
    request = classify(question, snapshot_id=SNAP, semantic_config_version=SEM)
    assert request is not None and request.wants == frozenset({"explain", "chart"})
    assert [(s.agent, s.depends_on) for s in build_plan(request, "t_1").steps] == [
        ("data", ()), ("insight", ("B1",)), ("chart", ("B2",))]
