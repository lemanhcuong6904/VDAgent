"""The Jev quality gate over OpenRouter's decisions endpoint, faked at the HTTP layer."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ..judge import PASS_THRESHOLD, REVIEW, JevJudge, Verdict

URL = "http://jev.test/api/alpha/decisions"


def jev_answers(noul: float, choice: str = "none") -> dict[str, Any]:
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "acceptable": {"type": "noul", "noul": noul},
            "problem": {"type": "choice", "choice": choice, "probabilities": {choice: 0.8}, "confidence": 0.8},
        },
    }


def judge_with(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[JevJudge, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    judge = JevJudge(url=URL, api_key="sk-test", model="typesafe/jev-1.13", transport=httpx.MockTransport(record))
    return judge, seen


async def test_asks_jev_for_an_acceptability_probability_and_the_main_problem() -> None:
    judge, seen = judge_with(lambda r: httpx.Response(200, json=jev_answers(0.8)))
    await judge.assess("[from: user] chart revenue", "Chart ch_1 (ds_1).", ["ds_1", "ch_1"])

    (request,) = seen
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "typesafe/jev-1.13"
    assert body["state"] == {"request": "[from: user] chart revenue", "answer": "Chart ch_1 (ds_1).", "artifacts": ["ds_1", "ch_1"]}
    assert body["questions"]["acceptable"]["type"] == "noul"
    assert set(body["questions"]["acceptable"]["criteria"]) == {"true", "false"}
    assert body["questions"]["problem"]["type"] == "choice"
    assert set(body["questions"]["problem"]["criteria"]) == set(REVIEW)


@pytest.mark.parametrize(("noul", "passed"), [(PASS_THRESHOLD, True), (PASS_THRESHOLD - 0.01, False), (0.97, True)])
async def test_the_draft_passes_at_or_above_the_threshold(noul: float, passed: bool) -> None:
    judge, _ = judge_with(lambda r: httpx.Response(200, json=jev_answers(noul, "missing_part")))
    verdict = await judge.assess("q", "a", [])
    assert verdict == Verdict(acceptable=noul, problem="missing_part")
    assert verdict.passed is passed


@pytest.mark.parametrize(
    "respond",
    [
        lambda r: httpx.Response(500, json={"error": {"message": "upstream down"}}),
        lambda r: httpx.Response(200, json={"answers": {}}),
        lambda r: httpx.Response(200, json={"answers": {"acceptable": {"type": "noul", "noul": "high"}}}),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("timed out", request=r)),
    ],
    ids=["http-error", "missing-answer", "malformed-noul", "not-json", "timeout"],
)
async def test_an_unusable_jev_reply_counts_as_a_pass(respond: Callable[[httpx.Request], httpx.Response]) -> None:
    judge, _ = judge_with(respond)
    verdict = await judge.assess("q", "a", [])
    assert verdict.acceptable is None and verdict.passed


def test_each_problem_has_its_own_review_and_unknown_problems_get_the_generic_one() -> None:
    assert Verdict(0.1, "missing_part").review == REVIEW["missing_part"]
    assert Verdict(0.1, "no_numbers").review != REVIEW["missing_part"]
    assert Verdict(0.1, None).review == REVIEW["none"]
    assert Verdict(0.1, "something_new").review == REVIEW["none"]
