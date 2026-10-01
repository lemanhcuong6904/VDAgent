"""Report agent entry point.

StepSpec requests use the deterministic offline report path. Direct chat uses a restricted MCP
tool set and a LangGraph turn with a Jev quality gate; the final answer is returned as
`AgentReport@1`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, convert_to_messages
from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from vdagent_agentkit.mcp_client import JsonTools
from vdagent_contracts.messages import ContractMessage, StepSpec, parse_incoming
from vdagent_contracts.reports import AgentReport, ReportError, render_agent_report
from vdagent_sdk import SEND_TO_AGENT, Agent, AgentTimeoutError, InvocationContext, Message, Peer

from .graph import ALLOWED_DIRECT_CHAT_TOOLS, STEP_LIMIT_TEXT, ReportTurn
from .judge import JevJudge, Judge
from .mcp_client import McpSessionFactory, open_mcp_session, openai_tool_schema
from .settings import DEFAULT_LLM_TIMEOUT_S, load_settings

__all__ = ["DESCRIPTION", "NAME", "STEP_LIMIT_TEXT", "LangGraphAgent", "build_agent"]

NAME = "report"
DESCRIPTION = "Builds formatted reports with charts."

PROMPTS_DIR = Path(__file__).parent / "prompts"
SUMMARY_HEADING = "## Summary of earlier work with this user"
COMPACT_TOOL_TEXT_CHARS = 2_000


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def build_system_prompt(prompt: str, summary: str) -> str:
    if not summary.strip():
        return prompt
    return f"{prompt}\n\n{SUMMARY_HEADING}\n{summary.strip()}"


def send_to_agent_tool(peers: Sequence[Peer]) -> dict[str, Any]:
    roster = "\n".join(f"- {p.name}: {p.description}" for p in peers)
    return {
        "type": "function",
        "function": {
            "name": SEND_TO_AGENT,
            "description": (
                "Send a message to another agent and wait for its reply. "
                f"The reply is returned as this tool's result. Agents:\n{roster}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "enum": [p.name for p in peers]},
                    "message": {
                        "type": "string",
                        "description": "Self-contained request, including any dataset ids it needs.",
                    },
                },
                "required": ["agent", "message"],
            },
        },
    }


def render_for_compaction(previous_summary: str, messages: Sequence[Message]) -> str:
    lines = ["Previous summary:", previous_summary.strip() or "(none)", "", "Messages to fold in:"]
    for msg in messages:
        if msg["role"] == "user":
            lines.append(f"[inbound] {msg['content']}")
        elif msg["role"] == "assistant":
            if msg.get("content"):
                lines.append(f"[you] {msg['content']}")
            for tc in msg.get("tool_calls") or []:
                lines.append(f"[you called {tc['function']['name']}] {tc['function']['arguments']}")
        elif msg["role"] == "tool":
            content = msg["content"]
            if len(content) > COMPACT_TOOL_TEXT_CHARS:
                content = content[:COMPACT_TOOL_TEXT_CHARS] + "…[truncated]"
            lines.append(f"[tool result] {content}")
    return "\n".join(lines)


class LangGraphAgent:
    def __init__(
        self,
        *,
        model: BaseChatModel,
        judge: Judge,
        mcp_session_factory: McpSessionFactory = open_mcp_session,
        system_prompt: str,
        compact_prompt: str,
        timeout_s: float = DEFAULT_LLM_TIMEOUT_S,
        direct_chat: bool = False,
    ) -> None:
        self._model = model
        self._judge = judge
        self._mcp_session_factory = mcp_session_factory
        self._system_prompt = system_prompt
        self._compact_prompt = compact_prompt
        self._timeout_s = timeout_s
        self._direct_chat = direct_chat

    async def invoke(self, ctx: InvocationContext, direct_chat: bool | None = None) -> None:
        is_direct = self._direct_chat if direct_chat is None else direct_chat
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            all_tools = await mcp.list_tools()
            if is_direct:
                mcp_tools = [t for t in all_tools if t.name in ALLOWED_DIRECT_CHAT_TOOLS]
                tools = [openai_tool_schema(t) for t in mcp_tools]
            else:
                mcp_tools = [t for t in all_tools if t.name != SEND_TO_AGENT]
                tools = [openai_tool_schema(t) for t in mcp_tools]
                if ctx.peers:
                    tools.append(send_to_agent_tool(ctx.peers))
            turn = ReportTurn(
                ctx=ctx,
                mcp=mcp,
                model=self._model,
                tools=tools,
                mcp_tool_names={t.name for t in mcp_tools},
                judge=self._judge,
                system_prompt=build_system_prompt(self._system_prompt, ctx.summary),
                timeout_s=self._timeout_s,
                direct_chat=is_direct,
            )
            state = {"messages": convert_to_messages(ctx.history)}
            await turn.graph().ainvoke(state, {"recursion_limit": 3 * ctx.max_steps + 10})

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        prompt = [
            SystemMessage(self._compact_prompt),
            HumanMessage(render_for_compaction(previous_summary, messages)),
        ]
        try:
            async with asyncio.timeout(self._timeout_s):
                reply = await self._model.ainvoke(prompt)
        except (TimeoutError, openai.APITimeoutError) as exc:
            raise AgentTimeoutError(f"model call timed out after {self._timeout_s:g}s") from exc
        return reply.text.strip()


NO_LLM_TEXT = (
    "Report đang chạy không có LLM (REPORT_LLM=off): chỉ nhận StepSpec@1 draft_report với ít nhất một artifact"
    " insight hoặc comparison đã ghim hash; chart_spec là tùy chọn. Chat tự do cần cấu hình LLM trong agents/report/.env."
)


class ReportAgent(LangGraphAgent):
    """WS6: `StepSpec@1 draft_report` → deterministic, evidence-checked report (stepspec.py); anything else → the
    LangGraph turn when a model is configured, else an explanation. `model=None` = offline Report Mode only."""

    def __init__(self, *, model: BaseChatModel | None, judge: Judge | None,
                 mcp_session_factory: McpSessionFactory = open_mcp_session, system_prompt: str, compact_prompt: str,
                 timeout_s: float = DEFAULT_LLM_TIMEOUT_S) -> None:
        super().__init__(model=model, judge=judge, mcp_session_factory=mcp_session_factory,  # pyright: ignore[reportArgumentType]
                         system_prompt=system_prompt, compact_prompt=compact_prompt, timeout_s=timeout_s, direct_chat=True)
        self._has_llm = model is not None and judge is not None

    @property
    def has_llm(self) -> bool:
        return self._has_llm

    async def invoke(self, ctx: InvocationContext) -> None:
        text = str(ctx.history[-1].get("content") or "") if ctx.history else ""
        try:
            incoming = parse_incoming(text)
        except ValueError as exc:
            text_err = str(exc)
            summary = "Yêu cầu có cấu trúc không hợp lệ; cần gửi một contract được hỗ trợ."
            report = AgentReport(
                state="rejected",
                summary=summary,
                error=ReportError(code="INVALID_CONTRACT", message=text_err),
            )
            await ctx.emit_assistant(render_agent_report(report.summary, report))
            return
        if isinstance(incoming, ContractMessage):
            await ctx.emit_assistant(await self._contract(ctx, incoming))
            return
        if not self._has_llm:
            report = AgentReport(
                state="rejected",
                summary=NO_LLM_TEXT,
                error=ReportError(code="LLM_REQUIRED", message=NO_LLM_TEXT),
            )
            await ctx.emit_assistant(render_agent_report(report.summary, report))
            return
        await super().invoke(ctx, direct_chat=True)

    async def _contract(self, ctx: InvocationContext, message: ContractMessage) -> str:
        from .stepspec import run_step

        if message.contract != "StepSpec@1":
            text = f"Report chỉ nhận StepSpec@1; nhận được {message.contract}."
            report = AgentReport(state="rejected", summary=text, error=ReportError(code="UNSUPPORTED_CONTRACT", message=text))
        else:
            try:
                step = StepSpec.model_validate(message.data)
            except ValidationError as exc:
                report = AgentReport(state="rejected", summary="StepSpec@1 không hợp lệ.",
                                     error=ReportError(code="INVALID_STEPSPEC", message=f"{exc.error_count()} error(s)"))
            else:
                async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
                    report = await run_step(step, JsonTools(mcp))
        head = report.summary or ("Đã hoàn tất xử lý yêu cầu." if report.state == "completed" else "Không thể hoàn tất yêu cầu.")
        return render_agent_report(head, report)

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        if not self._has_llm:
            return previous_summary
        return await super().compact(previous_summary, messages)


def build_agent(env: Mapping[str, str]) -> Agent:
    """Raises `PluginConfigError` naming the missing or invalid setting (unless `REPORT_LLM=off`)."""
    if (env.get("REPORT_LLM") or "").strip().lower() == "off":
        return ReportAgent(model=None, judge=None, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"))
    settings = load_settings(env)
    for noisy in ("httpx", "openai"):  # per-request INFO lines drown out agent logs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    model = ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.openai_base_url,
        api_key=SecretStr(settings.openai_api_key),
        timeout=settings.llm_timeout_s,
    )
    judge = JevJudge(url=settings.jev_decisions_url, api_key=settings.openai_api_key, model=settings.judge_model)
    return ReportAgent(
        model=model,
        judge=judge,
        system_prompt=load_prompt("system"),
        compact_prompt=load_prompt("compact"),
        timeout_s=settings.llm_timeout_s,
    )
