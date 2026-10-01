"""The narrator: turns the real trace of a Data step into natural language, with no result written in advance.

`TemplateNarrator` builds each sentence from the facts of the events (deterministic, free, no LLM).
`LlmNarrator` lets an LLM rewrite it, but only what the facts support: any number or identifier that is not in the
facts sends the sentence back to the template. The LLM only ever sees metadata (tables, row counts, codes), never rows.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from vdagent_data.llm import AssistantMessage, LLMTimeoutError
from vdagent_data.narrate import Beat, LlmNarrator, Task, TemplateNarrator, group_beats, numbers_supported, sources_of, tool_calls_of
from vdagent_data.steps import run_step
from vdagent_data.tests.conftest import McpPort
from vdagent_data.tests.test_steps import step
from vdagent_data.trace import TraceEvent

SUBJECT_ONLY = {"subject_unit_code": "A12-08"}
TASK = Task(operation="fetch_units", question="Vì sao căn A12-08 bán chậm?")


class Recorder:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


async def trace_of(port: McpPort, **kwargs: Any) -> list[TraceEvent]:
    rec = Recorder()
    await run_step(step(**kwargs), port, observer=rec)
    return rec.events


class FakeLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]], str]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: str) -> AssistantMessage:
        self.calls.append((messages, tools, tool_choice))
        if isinstance(self.reply, Exception):
            raise self.reply
        return AssistantMessage(content=self.reply)


# ---- grouping ---------------------------------------------------------------------------------------------------------


async def test_events_group_into_one_beat_per_phase_in_order(alice: McpPort) -> None:
    events = await trace_of(alice, spec=SUBJECT_ONLY)
    beats = group_beats(events)
    assert [b.phase for b in beats] == ["intake", "snapshot", "resolve", "fetch", "funnel", "check", "write", "done"]
    assert sum(len(b.events) for b in beats) == len(events)
    [fetch] = [b for b in beats if b.phase == "fetch"]
    assert [e.facts["table"] for e in fetch.events if e.state == "end"] == [
        "fact_unit_inventory_snapshot", "dm_unit_friction_diagnostics", "unit_diagnostic_causes",
        "dim_project_profile", "dim_zone_master", "dim_sales_channel"]


def test_no_events_no_beats() -> None:
    assert group_beats([]) == []


# ---- the template narrator: every sentence comes from the facts -------------------------------------------------------


async def test_each_beat_tells_what_really_happened(alice: McpPort) -> None:
    beats = {b.phase: b for b in group_beats(await trace_of(alice, spec=SUBJECT_ONLY))}
    say = {phase: await TemplateNarrator().narrate(beat, TASK) for phase, beat in beats.items()}
    assert "A12-08" in say["intake"] and "fetch_units" in say["intake"] and "SNAP-2026-09-28" in say["intake"]
    assert "PRJ-X" in say["intake"]  # the scope the Backend gave
    assert "SNAP-2026-09-28" in say["snapshot"] and "2026-09-28" in say["snapshot"] and "sc-1" in say["snapshot"]
    assert "min_group_size" in say["snapshot"]  # a pending threshold is named, not hidden
    assert "dim_unit_master" in say["resolve"] and "1 dòng" in say["resolve"]
    for table in ("fact_unit_inventory_snapshot", "dm_unit_friction_diagnostics", "dim_sales_channel"):
        assert table in say["fetch"]
    assert "fact_sales_funnel_daily" in say["funnel"]
    assert "dq" in say["write"] and "dataset" in say["write"] and "metric" in say["write"]
    assert "3" in say["done"] and "gói" in say["done"]


async def test_the_words_follow_the_facts_not_a_script(alice: McpPort) -> None:
    [resolve] = [b for b in group_beats(await trace_of(alice, spec=SUBJECT_ONLY)) if b.phase == "resolve"]
    changed = Beat(phase="resolve", events=tuple(
        TraceEvent(e.stage, e.state, e.call_id, e.purpose, {**e.facts, **({"rows": 7} if e.state == "end" else {})},
                   phase=e.phase) for e in resolve.events))
    assert "1 dòng" in await TemplateNarrator().narrate(resolve, TASK)
    assert "7 dòng" in await TemplateNarrator().narrate(changed, TASK)


async def test_a_failure_is_told_with_its_code(alice: McpPort) -> None:
    beats = group_beats(await trace_of(alice, spec={"subject_unit_code": "ZZ9-99"}))
    assert [b.phase for b in beats][-2:] == ["resolve", "fail"]
    text = await TemplateNarrator().narrate(beats[-1], Task("fetch_units", "Vì sao căn ZZ9-99 bán chậm?"))
    assert "UNIT_NOT_FOUND" in text and "failed" in text
    assert "0 dòng" in await TemplateNarrator().narrate(beats[-2], TASK)


async def test_every_number_and_identifier_in_a_template_sentence_is_in_the_facts(alice: McpPort) -> None:
    for kwargs in ({"spec": SUBJECT_ONLY}, {"spec": {"subject_unit_code": "ZZ9-99"}},
                   {"operation": "aggregate_metrics", "spec": {"metrics": ["dom_days"], "group_by": ["zone_key"]}}):
        events = await trace_of(alice, **kwargs)
        for beat in group_beats(events):
            text = await TemplateNarrator().narrate(beat, TASK)
            assert text.strip() and "```" not in text
            assert numbers_supported(text, sources_of(beat, TASK)), (beat.phase, text)


async def test_a_table_read_twice_is_named_once(alice: McpPort) -> None:
    beats = {b.phase: b for b in group_beats(await trace_of(alice))}  # the default step also reads the peer candidates
    text = await TemplateNarrator().narrate(beats["resolve"], TASK)
    assert text.count("dim_unit_master (") == 1 and " và " in text.split("Mục đích")[0]
    assert "1 dòng" in text


async def test_the_limitations_of_an_artifact_are_named_not_counted(alice: McpPort) -> None:
    beats = {b.phase: b for b in group_beats(await trace_of(alice, spec=SUBJECT_ONLY))}
    text = await TemplateNarrator().narrate(beats["write"], TASK)
    for code in ("BLOCKED:D2b_segment_mapping", "SYNTHETIC_SOURCE:net_area_m2", "METRIC_UNAVAILABLE:discount_pct"):
        assert code in text
    assert numbers_supported(text, sources_of(beats["write"], TASK))


async def test_the_tool_calls_of_a_beat_are_the_real_ones(alice: McpPort) -> None:
    beats = {b.phase: b for b in group_beats(await trace_of(alice, spec=SUBJECT_ONLY))}
    calls = tool_calls_of(beats["fetch"])
    assert [c.name for c, _ in calls] == ["re_run_query"] * 6
    assert len({c.id for c, _ in calls}) == 6
    for call, result in calls:
        assert json.loads(call.arguments_json)["table"] and json.loads(result)["rows"] >= 0
    writes = tool_calls_of(beats["write"])
    assert [c.name for c, _ in writes] == ["artifact_put"] * 3
    assert all(json.loads(r)["artifact_id"].startswith("art_") for _, r in writes)
    assert tool_calls_of(beats["intake"]) == [] and tool_calls_of(beats["check"]) == []


# ---- fact check -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "Đã đọc 3.260 căn", "Kỳ chốt 30/06/2026", "Đọc dim_unit_master: 1 dòng", "Lưu art_004a54a06b03@1",
])
def test_numbers_that_the_facts_support_pass(text: str) -> None:
    sources = ["3260", "2026-06-30", "dim_unit_master", "1", "art_004a54a06b03", "SNAP-20260630-01"]
    assert numbers_supported(text, sources)


@pytest.mark.parametrize("text", [
    "Đã đọc 3.261 căn", "Kỳ chốt 01/07/2026", "Đọc dim_zone_master: 1 dòng", "Lưu art_ffffffffffff@1", "Có 12 cảnh báo",
])
def test_numbers_or_identifiers_the_facts_do_not_have_fail(text: str) -> None:
    sources = ["3260", "2026-06-30", "dim_unit_master", "1", "art_004a54a06b03"]
    assert not numbers_supported(text, sources)


# ---- the LLM narrator: rewrites, but only what the facts support ------------------------------------------------------


async def beat_of(port: McpPort, phase: str) -> Beat:
    return next(b for b in group_beats(await trace_of(port, spec=SUBJECT_ONLY)) if b.phase == phase)


async def test_a_supported_llm_sentence_is_used(alice: McpPort) -> None:
    beat = await beat_of(alice, "resolve")
    llm = FakeLLM("Mình đã tìm trong dim_unit_master và thấy đúng 1 dòng khớp căn A12-08.")
    text = await LlmNarrator(llm, TemplateNarrator()).narrate(beat, TASK)
    assert text == "Mình đã tìm trong dim_unit_master và thấy đúng 1 dòng khớp căn A12-08."


@pytest.mark.parametrize("reply", [
    "Mình thấy 42 dòng khớp trong dim_unit_master.",  # a number that is not a fact
    "Đã đọc bảng dim_secret_table.",  # an identifier that is not a fact
    "Xong:\n```json\n{}\n```",  # code fences would break the AgentReport parser
    "   ",
    "x" * 2000,
])
async def test_an_unsupported_llm_sentence_falls_back_to_the_template(alice: McpPort, reply: str) -> None:
    beat = await beat_of(alice, "resolve")
    expected = await TemplateNarrator().narrate(beat, TASK)
    assert await LlmNarrator(FakeLLM(reply), TemplateNarrator()).narrate(beat, TASK) == expected


@pytest.mark.parametrize("error", [RuntimeError("boom"), LLMTimeoutError("slow")])
async def test_an_llm_failure_falls_back_to_the_template(alice: McpPort, error: Exception) -> None:
    beat = await beat_of(alice, "snapshot")
    assert await LlmNarrator(FakeLLM(error), TemplateNarrator()).narrate(beat, TASK) == await TemplateNarrator().narrate(beat, TASK)


async def test_a_slow_llm_is_cut_off(alice: McpPort) -> None:
    class Slow:
        async def complete(self, messages: Any, tools: Any, tool_choice: Any) -> AssistantMessage:
            await asyncio.sleep(5)
            return AssistantMessage(content="muộn")

    beat = await beat_of(alice, "resolve")
    text = await LlmNarrator(Slow(), TemplateNarrator(), timeout_s=0.05).narrate(beat, TASK)  # type: ignore[arg-type]
    assert text == await TemplateNarrator().narrate(beat, TASK)


async def test_the_llm_sees_the_task_and_the_facts_and_no_tools(alice: McpPort) -> None:
    beat = await beat_of(alice, "resolve")
    llm = FakeLLM("Đã đọc dim_unit_master: 1 dòng.")
    await LlmNarrator(llm, TemplateNarrator(), system_prompt="SYS").narrate(beat, TASK)
    [(messages, tools, _)] = llm.calls
    assert tools == [] and messages[0] == {"role": "system", "content": "SYS"}
    prompt = json.loads(messages[-1]["content"])
    assert prompt["nhiem_vu"] == {"operation": "fetch_units", "cau_hoi_goc": "Vì sao căn A12-08 bán chậm?"}
    assert prompt["giai_doan"] == "resolve" and prompt["ban_nhap"]
    assert {e["facts"]["table"] for e in prompt["su_kien"] if "table" in e["facts"]} == {"dim_unit_master"}
    blob = json.dumps(prompt, ensure_ascii=False)
    assert "63.02" not in blob and "72500000" not in blob  # row values never reach the LLM
