"""The quality gate: Jev (TypeSafe's "System One" decisions model) judges a draft answer.

Jev is not a chat model: OpenRouter serves it on its decisions endpoint, not `chat/completions`.
It returns typed, calibrated answers: here a `noul` (probability that the draft is acceptable)
and a `choice` (its main problem). The graph branches on them; the problem picks the review
message for the one revision.

An unusable reply (HTTP error, timeout, malformed answer) counts as a pass: a judge outage must
never block an answer.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

PASS_THRESHOLD = 0.5
JEV_TIMEOUT_S = 10.0

REVIEW: dict[str, str] = {
    "none": "A reviewer judged this answer not good enough to send. Improve it: answer every part of the "
    "request, cite the chart and report ids you created, and quote the key numbers.",
    "missing_part": "A reviewer found that your answer misses part of the request. Cover every part of it, "
    "creating any missing chart or report.",
    "unsupported_claim": "A reviewer found claims your work does not back. Cite only ids you created or received "
    "in this turn, and only numbers the datasets show.",
    "no_numbers": "A reviewer found your answer vague. Quote the key numbers (values, changes, shares) and the "
    "ids of the charts and report that show them.",
    "unclear": "A reviewer found your answer hard to follow. Restate it as a short, well-structured summary: "
    "what you made (ids) and what it shows.",
}

_CRITERIA: dict[str, str] = {
    "none": "No real weakness: it answers the whole request with ids and numbers.",
    "missing_part": "A part of the request (a period, segment, chart or report) is not addressed.",
    "unsupported_claim": "It cites ids not in `artifacts` or states numbers nothing in the turn backs.",
    "no_numbers": "It lacks the key numbers or the ids of what was created.",
    "unclear": "It is hard to follow or badly structured.",
}

QUESTIONS: dict[str, Any] = {
    "acceptable": {
        "type": "noul",
        "instructions": "Is this answer acceptable to send back to the requester as the result of the request?",
        "criteria": {
            "true": "It answers every part of the request, cites the chart/report ids from `artifacts` "
            "it created, and quotes the key numbers.",
            "false": "It misses part of the request, cites no or unknown ids, or gives vague numbers.",
        },
    },
    "problem": {
        "type": "choice",
        "instructions": "What is the main weakness of the answer?",
        "criteria": _CRITERIA,
    },
}


@dataclass(frozen=True)
class Verdict:
    acceptable: float | None
    """Jev's probability that the draft is acceptable; None if Jev gave no usable answer."""
    problem: str | None

    @property
    def passed(self) -> bool:
        return self.acceptable is None or self.acceptable >= PASS_THRESHOLD

    @property
    def review(self) -> str:
        return REVIEW.get(self.problem or "none", REVIEW["none"])


class Judge(Protocol):
    async def assess(self, request: str, answer: str, artifacts: Sequence[str]) -> Verdict: ...


class JevJudge:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        timeout_s: float = JEV_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._timeout_s = timeout_s
        self._transport = transport

    async def assess(self, request: str, answer: str, artifacts: Sequence[str]) -> Verdict:
        body = {
            "model": self._model,
            "state": {"request": request, "answer": answer, "artifacts": list(artifacts)},
            "questions": QUESTIONS,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
                response = await client.post(self._url, json=body, headers=self._headers)
                response.raise_for_status()
                answers = response.json()["answers"]
            acceptable = answers["acceptable"]["noul"]
            if isinstance(acceptable, bool) or not isinstance(acceptable, int | float):
                raise ValueError(f"acceptable.noul is not a number: {acceptable!r}")
            problem = answers.get("problem", {}).get("choice")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("jev: no usable verdict, passing the draft: %s", exc)
            return Verdict(acceptable=None, problem=None)
        verdict = Verdict(acceptable=float(acceptable), problem=problem if isinstance(problem, str) else None)
        log.info(
            "jev: acceptable=%.2f problem=%s (%s) → %s",
            verdict.acceptable,
            verdict.problem,
            answers.get("problem", {}).get("probabilities"),
            "pass" if verdict.passed else "revise",
        )
        return verdict
