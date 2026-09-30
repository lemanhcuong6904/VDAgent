"""StepSpec@1 path: the report summary may carry a model-written sentence, always checked by `check_phrase`.

The artifacts stay deterministic (no model text inside them); a missing or misbehaving model only costs the sentence.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from typing import Any

from vdagent_compare.llm import LLMUnavailableError
from vdagent_compare.stepspec import run_step
from vdagent_compare.tests.test_agent import FakeLLM
from vdagent_compare.tests.test_dw_integration import compare_step, data_refs
from vdagent_data.tests.conftest import McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)

GOOD = "A12-08 có DOM là 138 ngày, cao hơn trung vị của nhóm tương đồng."
TEMPLATE = "So sánh A12-08 với"


def writes(text: str) -> dict[str, Any]:
    return {"text": text}


async def run(port: McpPort, llm: FakeLLM | None):
    refs = await data_refs(port)
    return await run_step(compare_step(refs), port.as_agent("compare"), llm=llm)


async def stored(port: McpPort, report: Any, kind: str) -> dict[str, Any]:
    [ref] = [r for r in report.artifact_refs if r.artifact_type.value == kind]
    return await port.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})


async def test_model_sentence_joins_the_summary_and_stays_out_of_the_artifacts(alice: McpPort) -> None:
    llm = FakeLLM({"comparison_answer": [writes(GOOD)]})
    report = await run(alice, llm)
    assert report.state == "completed" and llm.names() == ["comparison_answer"]
    assert GOOD in report.summary and TEMPLATE in report.summary  # sentence added, template line kept
    for kind in ("peer_definition", "comparison"):
        assert GOOD not in json.dumps(await stored(alice, report, kind), ensure_ascii=False)


async def test_limits_sentence_from_the_code_comes_before_the_model(alice: McpPort) -> None:
    report = await run(alice, FakeLLM({"comparison_answer": [writes(GOOD)]}))
    sufficiency = (await stored(alice, report, "comparison"))["payload"]["dataSufficiency"]
    assert sufficiency["level"] in {"LIMITED", "INSUFFICIENT"}  # 5 peers: the hero is LIMITED
    assert report.summary.index(sufficiency["summary"]) < report.summary.index(GOOD)


async def test_invented_number_is_rewritten_once_then_dropped(alice: McpPort) -> None:
    llm = FakeLLM({"comparison_answer": [writes("A12-08 có DOM 9999 ngày."), writes("A12-08 có DOM 8888 ngày.")]})
    report = await run(alice, llm)
    assert report.state == "completed" and llm.names() == ["comparison_answer"] * 2
    assert "9999" not in report.summary and "8888" not in report.summary
    assert TEMPLATE in report.summary
    assert [r.artifact_type.value for r in report.artifact_refs] == ["peer_definition", "comparison"]


async def test_number_from_median_cannot_be_assigned_to_subject(alice: McpPort) -> None:
    class MedianAsSubject:
        calls = 0
        wrong = ""

        async def complete_json(self, messages, *, name, schema):
            row = next(line for line in messages[1]["content"].splitlines() if line.startswith("| DOM |"))
            cells = [cell.strip() for cell in row.split("|")[1:-1]]
            assert cells[1] != cells[2]  # subject DOM and group median differ
            self.wrong = f"A12-08 có DOM {cells[2]} ngày."
            self.calls += 1
            return writes(self.wrong)

    llm = MedianAsSubject()
    report = await run(alice, llm)
    assert report.state == "completed" and llm.calls == 2
    assert llm.wrong not in report.summary


async def test_causal_wording_is_refused(alice: McpPort) -> None:
    bad = writes("A12-08 bán chậm vì giá cao hơn nhóm, nên hãy giảm giá.")
    report = await run(alice, FakeLLM({"comparison_answer": [bad, bad]}))
    assert "hãy giảm giá" not in report.summary and TEMPLATE in report.summary


async def test_model_down_still_returns_every_number(alice: McpPort) -> None:
    report = await run(alice, FakeLLM({"comparison_answer": [LLMUnavailableError("down")]}))
    assert report.state == "completed" and report.partial is True
    sufficiency = (await stored(alice, report, "comparison"))["payload"]["dataSufficiency"]
    assert report.summary.startswith(sufficiency["summary"])
    assert TEMPLATE in report.summary
    assert [r.artifact_type.value for r in report.artifact_refs] == ["peer_definition", "comparison"]


async def test_no_model_means_no_call_and_the_template_summary(alice: McpPort) -> None:
    report = await run(alice, None)
    sufficiency = (await stored(alice, report, "comparison"))["payload"]["dataSufficiency"]
    assert report.state == "completed" and report.summary.startswith(sufficiency["summary"])
    assert TEMPLATE in report.summary


async def test_render_failure_after_artifacts_keeps_completed_report(alice: McpPort, monkeypatch) -> None:
    def broken_render(_result):
        raise KeyError("missing display label")

    monkeypatch.setattr("vdagent_compare.stepspec.render", broken_render)
    report = await run(alice, FakeLLM({}))
    assert report.state == "completed" and TEMPLATE in report.summary
    assert [r.artifact_type.value for r in report.artifact_refs] == ["peer_definition", "comparison"]


async def test_unexpected_model_error_after_artifacts_keeps_completed_report(alice: McpPort) -> None:
    report = await run(alice, FakeLLM({"comparison_answer": [RuntimeError("model unavailable")]}))
    assert report.state == "completed" and TEMPLATE in report.summary
    assert [r.artifact_type.value for r in report.artifact_refs] == ["peer_definition", "comparison"]


async def test_narration_timeout_keeps_completed_report(alice: McpPort, monkeypatch) -> None:
    class SlowLLM:
        async def complete_json(self, messages, *, name, schema):
            await asyncio.sleep(1)
            return writes(GOOD)

    monkeypatch.setattr("vdagent_compare.stepspec.PHRASE_TIMEOUT_S", 0.001)
    report = await run(alice, SlowLLM())
    assert report.state == "completed" and TEMPLATE in report.summary


async def test_orchestrator_cancellation_is_not_swallowed(alice: McpPort) -> None:
    class CanceledLLM:
        async def complete_json(self, messages, *, name, schema):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run(alice, CanceledLLM())


async def test_invalid_subject_never_reaches_the_model(alice: McpPort) -> None:
    refs = await data_refs(alice)
    llm = FakeLLM({})  # any call would raise AssertionError
    step = compare_step(refs, spec={"subject": {"entityType": "unit", "entityCode": "ZZ-99-99"}, "comparisonMode": "peer_group"})
    report = await run_step(step, alice.as_agent("compare"), llm=llm)
    assert report.state != "completed" and llm.calls == []
