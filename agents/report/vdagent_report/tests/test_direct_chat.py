"""Tests for Report Agent's direct-chat mode: tool boundaries, context ID checking,
AgentReport@1 envelope serialization, and REPORT_LLM=off rejection.
"""

from __future__ import annotations

import pytest
from vdagent_contracts.reports import ParseError, parse_agent_report
from vdagent_sdk import Message, Peer

from ..agent import ReportAgent, load_prompt
from ..graph import ALLOWED_DIRECT_CHAT_TOOLS, extract_context_ids
from ..judge import Verdict
from ..mcp_client import McpTool, ToolOutcome
from .test_agent import (
    COMPACT_PROMPT,
    FakeMcp,
    PASS,
    RecordingContext,
    ScriptedChat,
    ScriptedJudge,
    ai,
    chat,
)

DESCRIBE_DATASET = McpTool(
    name="describe_dataset",
    description="Column names and row counts of a dataset.",
    input_schema={"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]},
)

GET_DATASET_ROWS = McpTool(
    name="get_dataset_rows",
    description="Page of rows from a dataset.",
    input_schema={"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]},
)

ARTIFACT_GET = McpTool(
    name="artifact_get",
    description="Fetch a stored artifact.",
    input_schema={
        "type": "object",
        "properties": {"artifact_id": {"type": "string"}, "version": {"type": "integer"}},
        "required": ["artifact_id"],
    },
)

CREATE_CHART = McpTool(
    name="create_chart",
    description="Create a chart.",
    input_schema={"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]},
)

SAVE_REPORT = McpTool(
    name="save_report",
    description="Save a markdown report.",
    input_schema={"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
)


def make_report_agent(model: ScriptedChat, mcp: FakeMcp, judge: ScriptedJudge | None = None) -> ReportAgent:
    return ReportAgent(
        model=model,
        judge=judge or ScriptedJudge([PASS]),
        mcp_session_factory=mcp.factory,
        system_prompt=load_prompt("system"),
        compact_prompt=COMPACT_PROMPT,
    )


# --------------------------------------------------------------------------- Context ID extractor tests


def test_extract_context_ids() -> None:
    history: list[Message] = [
        {"role": "user", "content": "Phân tích căn hộ trong ds_sales_2025 và art_comparison_1"},
        {"role": "assistant", "content": "Đang xem dataset ds_sales_2025; có thể thử ds_hallucinated"},
        {"role": "tool", "content": "Kết quả từ ART-INSIGHT-abcd1234ef567890"},
    ]
    ids = extract_context_ids(history, summary="Đã tóm tắt ds_prev")
    assert "ds_sales_2025" in ids
    assert "art_comparison_1" in ids
    assert "ART-INSIGHT-abcd1234ef567890" in ids
    assert "ds_prev" in ids
    assert "ds_hallucinated" not in ids


# --------------------------------------------------------------------------- Offline REPORT_LLM=off


async def test_free_text_when_llm_off_returns_rejected_agent_report() -> None:
    agent = ReportAgent(
        model=None,
        judge=None,
        system_prompt="s",
        compact_prompt="c",
    )
    ctx = RecordingContext(history=[{"role": "user", "content": "Tóm tắt tình hình bán hàng"}])
    await agent.invoke(ctx)

    answers = ctx.answers()
    assert len(answers) == 1
    report = parse_agent_report(answers[0])
    assert not isinstance(report, ParseError)
    assert report.state == "rejected"
    assert report.error is not None
    assert report.error.code == "LLM_REQUIRED"
    assert "REPORT_LLM=off" in report.summary


async def test_invalid_json_contract_returns_rejected_agent_report() -> None:
    agent = ReportAgent(
        model=None,
        judge=None,
        system_prompt="s",
        compact_prompt="c",
    )
    ctx = RecordingContext(history=[{"role": "user", "content": '{"invalid_payload": true}'}])
    await agent.invoke(ctx)

    answers = ctx.answers()
    assert len(answers) == 1
    report = parse_agent_report(answers[0])
    assert not isinstance(report, ParseError)
    assert report.state == "rejected"
    assert report.error is not None
    assert report.error.code == "INVALID_CONTRACT"


# --------------------------------------------------------------------------- Direct chat with LLM


async def test_direct_chat_emits_agent_report_envelope() -> None:
    model, _ = chat(ai("Giải thích số liệu: Doanh thu căn hộ đạt mức ổn định theo dataset ds_1."))
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(tools=[DESCRIBE_DATASET], handlers={})
    agent = make_report_agent(model, mcp, judge)

    ctx = RecordingContext(history=[{"role": "user", "content": "Giải thích số liệu của ds_1"}])
    await agent.invoke(ctx)

    answers = ctx.answers()
    assert len(answers) == 1
    report = parse_agent_report(answers[0])
    assert not isinstance(report, ParseError)
    assert report.state == "completed"
    assert report.artifact_refs == []
    assert "Doanh thu căn hộ đạt mức ổn định" in report.summary


async def test_direct_chat_sanitizes_nested_json_fence_in_summary_preface() -> None:
    draft = '```json\n{"ok": true}\n```'
    model, _ = chat(ai(draft))
    mcp = FakeMcp(tools=[], handlers={})
    agent = make_report_agent(model, mcp)
    ctx = RecordingContext(history=[{"role": "user", "content": "Cho ví dụ JSON"}])

    await agent.invoke(ctx)

    (answer,) = ctx.answers()
    report = parse_agent_report(answer)
    assert not isinstance(report, ParseError)
    assert report.summary == draft


async def test_direct_chat_step_limit_is_reported_as_incomplete_not_successful_summary() -> None:
    model, _ = chat(ai("", ("c1", "describe_dataset", {"dataset_id": "ds_allowed"})))
    mcp = FakeMcp(tools=[DESCRIBE_DATASET], handlers={})
    agent = make_report_agent(model, mcp)
    ctx = RecordingContext(
        history=[{"role": "user", "content": "Mô tả ds_allowed"}],
        max_steps=1,
    )

    await agent.invoke(ctx)

    (answer,) = ctx.answers()
    report = parse_agent_report(answer)
    assert not isinstance(report, ParseError)
    assert report.state == "completed"
    assert report.partial is True
    assert report.summary != "Hoàn tất giải đáp."
    assert "Chưa thể hoàn tất" in report.summary


async def test_direct_chat_does_not_emit_a_draft_rejected_after_revision() -> None:
    model, _ = chat(ai("Số liệu không có nguồn là 123."), ai("Số liệu vẫn là 123."))
    rejected = Verdict(acceptable=0.1, problem="unsupported_claim")
    judge = ScriptedJudge([rejected, rejected])
    agent = make_report_agent(model, FakeMcp(tools=[], handlers={}), judge)
    ctx = RecordingContext(history=[{"role": "user", "content": "Số liệu là bao nhiêu?"}])

    await agent.invoke(ctx)

    (answer,) = ctx.answers()
    report = parse_agent_report(answer)
    assert not isinstance(report, ParseError)
    assert report.state == "rejected"
    assert report.error is not None and report.error.code == "QUALITY_GATE_REJECTED"
    assert "123" not in report.summary
    assert "123" not in answer.split("```json", 1)[0]


async def test_direct_chat_marks_unavailable_quality_gate_as_partial() -> None:
    model, _ = chat(ai("Nguồn hiện không có số liệu được hỏi."))
    agent = make_report_agent(
        model,
        FakeMcp(tools=[], handlers={}),
        ScriptedJudge([Verdict(acceptable=None, problem=None)]),
    )
    ctx = RecordingContext(history=[{"role": "user", "content": "Chỉ số là bao nhiêu?"}])

    await agent.invoke(ctx)

    (answer,) = ctx.answers()
    report = parse_agent_report(answer)
    assert not isinstance(report, ParseError)
    assert report.state == "completed"
    assert report.partial is True
    assert "QUALITY_GATE_UNAVAILABLE" in report.warnings


async def test_direct_chat_does_not_expose_or_allow_send_to_agent() -> None:
    model, rec = chat(ai("Chào bạn, tôi là Report agent."))
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(tools=[DESCRIBE_DATASET], handlers={})
    agent = make_report_agent(model, mcp, judge)

    ctx = RecordingContext(
        history=[{"role": "user", "content": "Chào agent"}],
        peers=[Peer("data", "data agent")],
    )
    await agent.invoke(ctx)

    (only_call,) = rec.calls
    tool_names = [t["function"]["name"] for t in only_call.tools]
    assert "send_to_agent" not in tool_names


async def test_direct_chat_does_not_expose_create_chart_or_save_report() -> None:
    model, rec = chat(ai("Tôi đã đọc dữ liệu."))
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(
        tools=[DESCRIBE_DATASET, GET_DATASET_ROWS, ARTIFACT_GET, CREATE_CHART, SAVE_REPORT],
        handlers={},
    )
    agent = make_report_agent(model, mcp, judge)

    ctx = RecordingContext(history=[{"role": "user", "content": "Đọc ds_test"}])
    await agent.invoke(ctx)

    (only_call,) = rec.calls
    tool_names = [t["function"]["name"] for t in only_call.tools]
    assert "create_chart" not in tool_names
    assert "save_report" not in tool_names
    assert set(tool_names).issubset(ALLOWED_DIRECT_CHAT_TOOLS)


async def test_direct_chat_tool_boundary_blocks_disallowed_tools_if_called() -> None:
    model, _ = chat(
        ai("", ("c1", "create_chart", {"dataset_id": "ds_1"})),
        ai("Không thể tạo biểu đồ trong chế độ này."),
    )
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(
        tools=[DESCRIBE_DATASET, CREATE_CHART],
        handlers={"create_chart": lambda a: ToolOutcome("ch_1")},
    )
    agent = make_report_agent(model, mcp, judge)

    ctx = RecordingContext(history=[{"role": "user", "content": "Vẽ biểu đồ cho ds_1"}])
    await agent.invoke(ctx)

    results = ctx.tool_results()
    assert "c1" in results
    assert "not permitted in direct chat" in results["c1"]


async def test_direct_chat_blocks_artifact_and_dataset_ids_not_in_context() -> None:
    model, _ = chat(
        ai(
            "",
            ("c1", "describe_dataset", {"dataset_id": "ds_forbidden"}),
            ("c2", "artifact_get", {"artifact_id": "art_forbidden", "version": 1}),
        ),
        ai("Đã kiểm tra nhưng ID không có trong ngữ cảnh."),
    )
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(
        tools=[DESCRIBE_DATASET, ARTIFACT_GET],
        handlers={
            "describe_dataset": lambda a: ToolOutcome('{"columns": ["a"]}'),
            "artifact_get": lambda a: ToolOutcome('{"payload": {}}'),
        },
    )
    agent = make_report_agent(model, mcp, judge)

    ctx = RecordingContext(history=[{"role": "user", "content": "Hãy phân tích ds_allowed"}])
    await agent.invoke(ctx)

    results = ctx.tool_results()
    assert "restricted to dataset ids present in context" in results["c1"]
    assert "restricted to artifact ids present in context" in results["c2"]


async def test_direct_chat_allows_dataset_and_artifact_ids_in_context() -> None:
    model, _ = chat(
        ai(
            "",
            ("c1", "describe_dataset", {"dataset_id": "ds_allowed"}),
            ("c2", "artifact_get", {"artifact_id": "art_allowed", "version": 1}),
        ),
        ai("Dữ liệu và artifact đã được đọc thành công."),
    )
    judge = ScriptedJudge([PASS])
    mcp = FakeMcp(
        tools=[DESCRIBE_DATASET, ARTIFACT_GET],
        handlers={
            "describe_dataset": lambda a: ToolOutcome('{"columns": ["revenue"]}'),
            "artifact_get": lambda a: ToolOutcome('{"payload": {"subject": "A12"}}'),
        },
    )
    agent = make_report_agent(model, mcp, judge)

    ctx = RecordingContext(
        history=[{"role": "user", "content": "Hãy xem ds_allowed và artifact art_allowed"}],
    )
    await agent.invoke(ctx)

    results = ctx.tool_results()
    assert "revenue" in results["c1"]
    assert "A12" in results["c2"]

    answers = ctx.answers()
    report = parse_agent_report(answers[0])
    assert not isinstance(report, ParseError)
    assert report.state == "completed"
