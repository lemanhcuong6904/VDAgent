"""S1 understand & resolve (build spec 02 §5): value index, closed-choice questions, reuse of answers, SPEC_MISMATCH."""

from __future__ import annotations

import pytest

from vdagent_contracts.messages import AnsweredChoice
from vdagent_data.pipeline.s1_resolve import Question, Resolution, resolve_step
from vdagent_data.pipeline.s0_intake import Failure
from vdagent_data.specs import AggregateMetricsSpec
from vdagent_data.tests.conftest import step
from vdagent_data.tests.fakes import DwMcp
from vdagent_data.value_index import Ambiguous, Match, NotFound, ValueIndex, load_index


@pytest.fixture
async def index(dw_path: str) -> ValueIndex:
    return await load_index(DwMcp(dw_path))


def spec(*mentions: tuple[str, str], filters: list[str] | None = None) -> AggregateMetricsSpec:
    return AggregateMetricsSpec.model_validate({
        "objective": "x", "metrics": ["avg_dom_unsold"], "filters": filters or [],
        "scope": {"mentions": [{"text": t, "kind_hint": k} for t, k in mentions], "scope_all": False},
    })


def test_exact_match(index: ValueIndex) -> None:
    assert index.resolve("Tòa Landmark 1", "ZONE") == Match(kind="ZONE", ids=["ZN-A"], label="Tòa Landmark 1")
    assert index.resolve("A12-08", "UNIT") == Match(kind="UNIT", ids=["U-PRJ-X-A12-08"], label="A12-08")


def test_accent_free_match(index: ValueIndex) -> None:
    assert index.resolve("toa aqua 1", "UNKNOWN") == Match(kind="ZONE", ids=["ZN-C"], label="Tòa Aqua 1")
    assert index.resolve("a1208", "UNIT") == Match(kind="UNIT", ids=["U-PRJ-X-A12-08"], label="A12-08")


def test_fuzzy_match(index: ValueIndex) -> None:
    assert index.resolve("Khu do thi Song Xanh", "PROJECT") == Match(kind="PROJECT", ids=["PRJ-X"], label="Khu đô thị Sông Xanh")
    assert index.resolve("Landmark Plazza", "ZONE") == Match(kind="ZONE", ids=["ZN-B"], label="Landmark Plaza")


def test_landmark_ambiguous_two_choices(index: ValueIndex) -> None:  # V1
    result = index.resolve("Landmark", "ZONE")
    assert isinstance(result, Ambiguous)
    assert [(o.id, o.label) for o in result.options] == [("ZN-B", "Landmark Plaza"), ("ZN-A", "Tòa Landmark 1")]


async def test_entity_not_found_with_3_suggestions_question(dw_path: str) -> None:
    result = await resolve_step(step(original_question="DOM của Tòa Aquaa 9?"), spec(("Tòa Aquaa 9", "ZONE")), DwMcp(dw_path))
    assert isinstance(result, Question) and result.code == "ENTITY_NOT_FOUND"
    assert 1 <= len(result.options) <= 3 and result.options[0].id == "ZN-C"
    assert result.input_id == "B1:0"


async def test_entity_not_found_no_suggestion_error_spec_issue(dw_path: str) -> None:
    # PRJ-Y exists but is outside Alice's scope: the Backend hides it, so it reads exactly like an unknown name
    result = await resolve_step(step(original_question="Tòa Đồi Thông 1 bán chậm?"),
                                spec(("Tòa Đồi Thông 1", "ZONE")), DwMcp(dw_path))
    assert isinstance(result, Failure) and result.code == "ENTITY_NOT_FOUND"
    assert "PRJ-Y" not in result.reason


async def test_answered_choice_reused_same_run(dw_path: str) -> None:
    question = await resolve_step(step(original_question="DOM của Landmark?"), spec(("Landmark", "ZONE")), DwMcp(dw_path))
    assert isinstance(question, Question) and question.code == "AMBIGUOUS_REQUEST" and question.input_id == "B1:0"
    answered = step(step_id="B2", original_question="DOM của Landmark?",
                    answered_choices=[AnsweredChoice(input_id="B1:0", choice="ZN-A")])
    result = await resolve_step(answered, spec(("Landmark", "ZONE")), DwMcp(dw_path))
    assert isinstance(result, Resolution)
    assert result.scope_filters == {"zone_key": ["ZN-A"]}
    assert result.resolved["Landmark"]["ids"] == ["ZN-A"]


async def test_spec_mismatch_question_vs_filter(dw_path: str) -> None:
    contradicting = step(original_question="Căn nào của Tòa Landmark 1 bán chậm?")
    result = await resolve_step(contradicting, spec(("Tòa Landmark 1", "ZONE"), filters=["sold"]), DwMcp(dw_path))
    assert isinstance(result, Failure) and result.code == "SPEC_MISMATCH"
    foreign = await resolve_step(step(), spec(("Tòa Aqua 1", "ZONE")), DwMcp(dw_path))  # not in the question
    assert isinstance(foreign, Failure) and foreign.code == "SPEC_MISMATCH"
    fine = await resolve_step(contradicting, spec(("Tòa Landmark 1", "ZONE"), filters=["slow_moving"]), DwMcp(dw_path))
    assert isinstance(fine, Resolution) and fine.scope_filters == {"zone_key": ["ZN-A"]}
