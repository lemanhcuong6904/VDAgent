"""The Data Agent plugin (Data v02): one turn = one data step, answered with an AgentReport (system prompt §6.1).

A `StepSpec@1` JSON message runs the pipeline strictly. Free text (a user chatting with Data directly, or a peer
asking in words) is turned into a StepSpec by one structured LLM call, or answered with guidance. MCP calls are
harness steps, not model tool calls: the turn emits exactly one assistant step, the report; lineage lives in the
Data Package.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from vdagent_sdk import InvocationContext, Message, PluginConfigError

from vdagent_agentkit.llm import LlmError, LlmRouter
from vdagent_agentkit.mcp_client import McpSession, McpSessionFactory, open_mcp_session
from vdagent_agentkit.settings import load_llm_settings
from vdagent_contracts.messages import ContractMessage, FreeText, StepSpec, parse_incoming
from vdagent_contracts.reports import AgentReport, ReportError, render_agent_report
from vdagent_contracts.scope import UserContext
from vdagent_data.pipeline.machine import run_step

NAME = "data"
DESCRIPTION = (
    "Data Agent: runs one data step (StepSpec@1: fetch_units, aggregate_metrics, fetch_peer_candidates,"
    " fetch_unit_context) on the real-estate warehouse and returns a Data Package; also answers simple data questions."
)
PROMPTS_DIR = Path(__file__).parent / "prompts"
log = logging.getLogger(__name__)


class FreeTextRequest(BaseModel):
    """What the model may fill from a free-text question: names only, never SQL or scope."""

    model_config = ConfigDict(extra="forbid")
    answerable: bool
    guidance: str = ""
    operation: Literal["aggregate_metrics", "fetch_units"] = "aggregate_metrics"
    mentions: list[dict[str, str]] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)


def _free_text_prompt() -> str:
    from vdagent_data.semantic.loader import LAYER

    vocab = "\n".join(
        [f"metric {n}: {m.description}" for n, m in LAYER.metrics.items()]
        + [f"dimension {n}: {d.description}" for n, d in LAYER.dimensions.items()]
        + [f"filter {n}: {f.description}" for n, f in LAYER.filters.items()]
    )
    return (PROMPTS_DIR / "system.md").read_text(encoding="utf-8").strip() + "\n\nTừ vựng:\n" + vocab


def _summary_line(report: AgentReport) -> str:
    if report.state == "completed":
        return report.summary.splitlines()[0] if report.summary else "Đã chuẩn bị dữ liệu."
    if report.state == "input_required" and report.question:
        return report.question.text
    return report.error.message if report.error else "Không thực hiện được yêu cầu dữ liệu."


class DataAgent:
    def __init__(self, *, router: LlmRouter | None, mcp_session_factory: McpSessionFactory = open_mcp_session) -> None:
        self._router = router
        self._mcp = mcp_session_factory

    async def invoke(self, ctx: InvocationContext) -> None:
        text = ctx.history[-1]["content"] if ctx.history else ""
        async with self._mcp(ctx.mcp.url, ctx.mcp.token) as session:
            report = await self._handle(text, ctx, session)
        await ctx.emit_assistant(render_agent_report(_summary_line(report), report))

    async def _handle(self, text: str, ctx: InvocationContext, session: McpSession) -> AgentReport:
        try:
            incoming = parse_incoming(text)
        except ValueError as exc:
            return self._rejected("SPEC_MISMATCH", f"Yêu cầu JSON không hợp lệ: {exc}")
        if isinstance(incoming, ContractMessage):
            if incoming.contract != "StepSpec@1":
                return self._rejected("OUT_OF_SCOPE", f"Data Agent không nhận hợp đồng {incoming.contract}.")
            try:
                step = StepSpec.model_validate(incoming.data)
            except ValidationError as exc:
                return self._rejected("SPEC_MISMATCH", f"StepSpec không hợp lệ: {exc.error_count()} lỗi.")
            return await run_step(step, session, self._router, user_id=ctx.user_id)
        assert isinstance(incoming, FreeText)
        return await self._free_text(incoming.text, ctx, session)

    @staticmethod
    def _rejected(code: str, message: str) -> AgentReport:
        return AgentReport(state="rejected", error=ReportError(code=code, message=message), summary=message)

    async def _free_text(self, question: str, ctx: InvocationContext, session: McpSession) -> AgentReport:
        if self._router is None:
            return self._rejected("LLM_UNAVAILABLE", "Hãy gửi yêu cầu dạng StepSpec@1; chế độ hỏi tự do cần mô hình ngôn ngữ.")
        try:
            parsed = await self._router.structured(FreeTextRequest, [
                {"role": "system", "content": _free_text_prompt()},
                {"role": "user", "content": f"<data>\n{question}\n</data>"},
            ])
        except LlmError as exc:
            code = "LLM_QUOTA_EXHAUSTED" if exc.agent_code == "LLM_QUOTA_EXHAUSTED" else "LLM_UNAVAILABLE"
            return AgentReport(state="failed", error=ReportError(code=code, message="Mô hình ngôn ngữ không dùng được.",
                                                                  retryable=True), summary="Mô hình ngôn ngữ không dùng được.")
        request = parsed.value
        if not request.answerable:
            return self._rejected("OUT_OF_SCOPE", request.guidance or "Câu hỏi nằm ngoài dữ liệu Data Agent có thể lấy.")
        outcome = await session.call_tool("get_user_context", {})
        context = UserContext.model_validate_json(outcome.text)
        spec: dict[str, Any] = {
            "objective": question[:300],
            "scope": {"mentions": request.mentions, "scope_all": not request.mentions},
            "filters": request.filters,
        }
        if request.operation == "aggregate_metrics":
            spec |= {"metrics": request.metrics, "group_by": request.group_by}
        plan_id = f"ADHOC-{ctx.invocation_id}"
        step = StepSpec(run_id=ctx.task_id, plan_id=plan_id, step_id="B1", idempotency_key=f"{plan_id}:B1",
                        operation=request.operation, spec=spec, user_context=context, original_question=question)
        return await run_step(step, session, self._router, user_id=ctx.user_id)

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        """Data keeps no conversational state: every step is self-contained (R1)."""
        return previous_summary


def build_agent(env: Mapping[str, str]) -> DataAgent:
    """LLM settings are optional: without them T1/T2 still run; T3, summaries by LLM and free text are off."""
    try:
        router: LlmRouter | None = load_llm_settings(env).router()
    except PluginConfigError as exc:
        log.warning("data agent without LLM (%s): T1/T2 only", exc)
        router = None
    return DataAgent(router=router)
