"""The Data agent narrates its own work to the person watching, in the SDK's own steps.

Every phase of a StepSpec turn becomes one assistant step (with the real tool calls of that phase and their results);
the last step is the answer the Orchestrator parses, unchanged: a short natural-language closing and one AgentReport
JSON fence. The narration never changes what the step computes, and `DATA_NARRATE=off` restores the single-step answer.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from vdagent_contracts.reports import AgentReport, parse_agent_report
from vdagent_data.agent import DataAgent, build_agent
from vdagent_data.llm import AssistantMessage
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_data.tests.test_agent_steps import Ctx as BaseCtx
from vdagent_data.tests.test_agent_steps import factory
from vdagent_data.tests.test_steps import step

SUBJECT_ONLY = {"subject_unit_code": "A12-08"}


class StrictCtx(BaseCtx):
    """Enforces the SDK ordering rules the Backend checks (`ContractViolation`), and records the whole turn."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.log: list[tuple[str, Any]] = []
        self._open: set[str] = set()

    async def emit_assistant(self, content: str, tool_calls: Any = ()) -> None:
        assert not self._open, f"tool calls {sorted(self._open)} of the previous step have no result yet"
        ids = [c.id for c in tool_calls]
        assert all(ids) and len(set(ids)) == len(ids), f"tool-call ids must be non-empty and unique, got {ids}"
        self._open = set(ids)
        self.log.append(("assistant", (content, list(tool_calls))))
        await super().emit_assistant(content, tool_calls)

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        assert tool_call_id in self._open, f"emit_tool_result({tool_call_id!r}): not an unresolved tool call of the latest step"
        self._open.discard(tool_call_id)
        self.log.append(("result", (tool_call_id, content)))
        await super().emit_tool_result(tool_call_id, content)


class FakeLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply, self.calls = reply, 0

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str) -> AssistantMessage:
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return AssistantMessage(content=self.reply)


def agent(tools: McpTools, **kwargs: Any) -> DataAgent:
    kwargs.setdefault("llm", None)
    return DataAgent(mcp_session_factory=factory(tools), system_prompt="x", compact_prompt="y", **kwargs)


async def turn(tools: McpTools, message: str | None = None, **kwargs: Any) -> StrictCtx:
    ctx = StrictCtx(message if message is not None else step(spec=SUBJECT_ONLY).model_dump_json())
    await agent(tools, **kwargs).invoke(ctx)
    assert not ctx._open, "invoke returned with unresolved tool calls"
    return ctx


def answer(ctx: StrictCtx) -> tuple[str, AgentReport]:
    content, calls = ctx.steps[-1]
    assert calls == []
    report = parse_agent_report(content)
    assert isinstance(report, AgentReport), report
    return content, report


# ---- what the person watching sees ------------------------------------------------------------------------------------


async def test_each_phase_is_a_step_and_the_last_step_is_the_answer(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools)
    assert 4 <= len(ctx.steps) <= 12
    assert all(text.strip() for text, _ in ctx.steps)
    content, report = answer(ctx)
    assert report.state == "completed" and len(report.artifact_refs) == 3
    assert content.count("```json") == 1 and not content.strip().startswith("```")  # a natural-language closing precedes the JSON


async def test_the_steps_tell_what_the_agent_really_did(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools)
    texts = [t for t, _ in ctx.steps[:-1]]
    joined = "\n".join(texts)
    for real in ("A12-08", "SNAP-2026-09-28", "PRJ-X", "dim_unit_master", "fact_unit_inventory_snapshot", "fact_sales_funnel_daily",
                 "dataset", "metric", "dq"):
        assert real in joined, real
    assert "3 gói" in ctx.steps[-1][0]  # the closing line comes from the done event, before the JSON


async def test_the_real_tool_calls_are_shown_with_their_results(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools)
    calls = [c for _, cs in ctx.steps for c in cs]
    assert [c.name for c in calls].count("re_run_query") >= 8 and [c.name for c in calls].count("artifact_put") == 3
    results = {v[0] for k, v in ctx.log if k == "result"}
    assert results == {c.id for c in calls}


async def test_the_answer_is_what_the_orchestrator_reads(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools)
    _, report = answer(ctx)
    assert report.step_id == "B1" and report.idempotency_key == "pl_ws2:B1" and report.snapshot_id == "SNAP-2026-09-28"


async def test_a_failed_step_is_narrated_and_still_ends_in_a_report(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, step(spec={"subject_unit_code": "ZZ9-99"}).model_dump_json())
    content, report = answer(ctx)
    assert report.state == "failed" and report.error is not None and report.error.code == "UNIT_NOT_FOUND"
    assert "UNIT_NOT_FOUND" in content.split("```json")[0]  # the closing line says what went wrong
    assert any("dim_unit_master" in t and "0 dòng" in t for t, _ in ctx.steps[:-1])


async def test_a_refused_step_is_told_too(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, step(spec=SUBJECT_ONLY, snapshot_id="SNAP-NOPE").model_dump_json())
    content, report = answer(ctx)
    assert report.state == "rejected" and "SNAPSHOT_UNKNOWN" in content.split("```json")[0]


async def test_a_peer_candidates_step_stays_within_the_step_budget(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, step().model_dump_json())
    assert len(ctx.steps) <= ctx.max_steps


# ---- narration never changes the work ---------------------------------------------------------------------------------


async def test_the_report_is_the_same_with_and_without_narration(mcp_tools: McpTools) -> None:
    on = answer(await turn(mcp_tools))[1]
    off = answer(await turn(mcp_tools, narrate=False))[1]
    assert (on.state, on.warnings, on.partial, sorted(r.artifact_type.value for r in on.artifact_refs)) == (
        off.state, off.warnings, off.partial, sorted(r.artifact_type.value for r in off.artifact_refs))


async def test_narrate_off_restores_the_single_step_answer(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, narrate=False)
    assert len(ctx.steps) == 1 and ctx.steps[0][1] == [] and ctx.results == []


async def test_free_text_is_not_narrated(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, "doanh thu theo vùng năm 2025?")
    assert len(ctx.steps) == 1 and "StepSpec@1" in ctx.steps[0][0]


# ---- with an LLM ------------------------------------------------------------------------------------------------------


async def test_a_supported_llm_sentence_replaces_the_template_line(mcp_tools: McpTools) -> None:
    llm = FakeLLM("Mình đã lưu xong 3 gói kết quả cho Orchestrator.")
    ctx = await turn(mcp_tools, llm=llm)
    assert llm.calls > 0
    assert ctx.steps[-1][0].startswith("Mình đã lưu xong 3 gói kết quả cho Orchestrator.")
    assert any("dim_unit_master" in t for t, _ in ctx.steps[:-1])  # lines the LLM could not support stay template lines


async def test_a_failing_llm_leaves_the_template_narration(mcp_tools: McpTools) -> None:
    ctx = await turn(mcp_tools, llm=FakeLLM(RuntimeError("no key")))
    assert answer(ctx)[1].state == "completed" and "3 gói" in ctx.steps[-1][0]


async def test_narrate_llm_off_never_calls_the_llm(mcp_tools: McpTools) -> None:
    llm = FakeLLM("Mình đã lưu xong 3 gói kết quả.")
    ctx = await turn(mcp_tools, llm=llm, narrate_llm=False)
    assert llm.calls == 0 and answer(ctx)[1].state == "completed"


# ---- configuration ----------------------------------------------------------------------------------------------------


def test_narration_is_on_by_default_and_switchable() -> None:
    assert build_agent({"DATA_LLM": "off"})._narrate is True  # type: ignore[attr-defined]
    assert build_agent({"DATA_LLM": "off", "DATA_NARRATE": "off"})._narrate is False  # type: ignore[attr-defined]
    with_llm = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://x/v1", "LLM_MODEL": "m"}
    assert build_agent(with_llm)._narrate_llm is True  # type: ignore[attr-defined]
    assert build_agent({**with_llm, "DATA_NARRATE_LLM": "off"})._narrate_llm is False  # type: ignore[attr-defined]


@pytest.mark.parametrize("value", ["off", "OFF", " Off "])
def test_the_off_switches_ignore_case_and_spaces(value: str) -> None:
    assert build_agent({"DATA_LLM": "off", "DATA_NARRATE": value})._narrate is False  # type: ignore[attr-defined]
