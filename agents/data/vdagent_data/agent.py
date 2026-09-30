"""This agent's brain.

A `StepSpec@1` message (WS2, D4) runs the deterministic real-estate path in `steps.py`: no LLM, one
`AgentReport@1` answer. Any other message keeps the legacy behaviour, a thin tool-calling loop over LiteLLM
with the Backend's MCP tools: open an MCP session, offer its tools plus `send_to_agent`, and step the model up
to `ctx.max_steps` times (`tool_choice="none"` on the last step). Every assistant step and tool result is
reported through `ctx`; tool calls of one step run concurrently. With `DATA_LLM=off` the plugin loads without
LLM settings and serves StepSpec requests only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from vdagent_contracts.messages import ContractMessage, StepSpec, parse_incoming
from vdagent_contracts.reports import AgentReport, render_agent_report
from vdagent_sdk import SEND_TO_AGENT, Agent, AgentTimeoutError, InvocationContext, Message, Peer, ToolCall

from .llm import AssistantMessage, LiteLLMClient, LLMClient, LLMTimeoutError, ToolChoice
from .mcp_client import (
    MCP_TOOL_TIMEOUT_S,
    McpSession,
    McpSessionFactory,
    open_mcp_session,
    openai_tool_schema,
    run_mcp_tool,
)
from .settings import load_settings
from .steps import ToolFailure, rejection, run_step

NAME = "data"
DESCRIPTION = (
    "Queries the warehouse; returns dataset ids. A StepSpec@1 JSON request (fetch_units, aggregate_metrics) reads the"
    " real-estate DW deterministically and returns dataset/metric/dq artifacts in an AgentReport@1."
)
STEPSPEC = "StepSpec@1"
NO_LLM_TEXT = (
    "Data đang chạy ở chế độ không có LLM (DATA_LLM=off): chỉ nhận yêu cầu có cấu trúc StepSpec@1"
    " (fetch_units, aggregate_metrics). Câu hỏi tự do cần cấu hình LLM trong agents/data/.env."
)

PROMPTS_DIR = Path(__file__).parent / "prompts"
SUMMARY_HEADING = "## Summary of earlier work with this user"
STEP_LIMIT_TEXT = "[step limit reached before I could finish; no further tool calls were made]"
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


class LiteLLMAgent:
    def __init__(
        self,
        *,
        llm: LLMClient,
        mcp_session_factory: McpSessionFactory = open_mcp_session,
        system_prompt: str,
        compact_prompt: str,
    ) -> None:
        self._llm = llm
        self._mcp_session_factory = mcp_session_factory
        self._system_prompt = system_prompt
        self._compact_prompt = compact_prompt

    async def _complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: ToolChoice
    ) -> AssistantMessage:
        try:
            return await self._llm.complete(messages, tools, tool_choice)
        except LLMTimeoutError as exc:
            raise AgentTimeoutError(str(exc)) from exc

    async def invoke(self, ctx: InvocationContext) -> None:
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            await _Turn(ctx, mcp, self._system_prompt, self._complete).run()

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        reply = await self._complete(
            [
                {"role": "system", "content": self._compact_prompt},
                {"role": "user", "content": render_for_compaction(previous_summary, messages)},
            ],
            [],
            "none",
        )
        return reply.content.strip()


class _Turn:
    """State of one `invoke` (kept off the agent object: one agent serves concurrent turns)."""

    def __init__(
        self,
        ctx: InvocationContext,
        mcp: McpSession,
        system_prompt: str,
        complete: Callable[[list[dict[str, Any]], list[dict[str, Any]], ToolChoice], Awaitable[AssistantMessage]],
    ) -> None:
        self._ctx = ctx
        self._mcp = mcp
        self._system_prompt = system_prompt
        self._complete = complete
        self._mcp_tool_names: set[str] = set()

    async def run(self) -> None:
        ctx = self._ctx
        tools: list[dict[str, Any]] = []
        for tool in await self._mcp.list_tools():
            if tool.name == SEND_TO_AGENT:
                continue
            self._mcp_tool_names.add(tool.name)
            tools.append(openai_tool_schema(tool))
        if ctx.peers:
            tools.append(send_to_agent_tool(ctx.peers))

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self._system_prompt, ctx.summary)},
            *ctx.history,
        ]
        for step in range(1, ctx.max_steps + 1):
            last_step = step == ctx.max_steps
            reply = await self._complete(messages, tools, "none" if last_step else "auto")
            if last_step and reply.tool_calls:
                # The model ignored tool_choice="none"; there is no step left to run the calls.
                reply = AssistantMessage(content=reply.content or STEP_LIMIT_TEXT)
            await ctx.emit_assistant(reply.content, reply.tool_calls)
            messages.append(reply.to_openai())
            if not reply.tool_calls:
                return
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(self._run_tool_call(tc)) for tc in reply.tool_calls]
            for tc, task in zip(reply.tool_calls, tasks, strict=True):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": task.result()})

    async def _run_tool_call(self, tc: ToolCall) -> str:
        content = await self._tool_content(tc)
        await self._ctx.emit_tool_result(tc.id, content)
        return content

    async def _tool_content(self, tc: ToolCall) -> str:
        try:
            arguments = json.loads(tc.arguments_json) if tc.arguments_json.strip() else {}
        except json.JSONDecodeError as exc:
            return f"error: invalid JSON arguments for '{tc.name}': {exc}"
        if not isinstance(arguments, dict):
            return f"error: arguments for '{tc.name}' must be a JSON object"

        if tc.name == SEND_TO_AGENT and self._ctx.peers:
            target, message = arguments.get("agent"), arguments.get("message")
            if not isinstance(target, str) or not target.strip():
                return "error: send_to_agent requires 'agent' (the name of the agent to call)"
            if not isinstance(message, str) or not message.strip():
                return "error: send_to_agent requires a non-empty 'message'"
            return await self._ctx.call_agent(tc.id, target.strip(), message)
        if tc.name in self._mcp_tool_names:
            return await run_mcp_tool(self._mcp, tc.name, arguments)
        return f"error: unknown tool '{tc.name}'"


class SessionTools:
    """The `steps.Tools` port over one MCP session (full JSON results: no truncation for the model)."""

    def __init__(self, session: McpSession) -> None:
        self._session = session

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        async with asyncio.timeout(MCP_TOOL_TIMEOUT_S):
            outcome = await self._session.call_tool(name, args)
        if outcome.is_error:
            raise ToolFailure(outcome.text)
        return json.loads(outcome.text)


def _inbound(ctx: InvocationContext) -> str:
    return str(ctx.history[-1].get("content") or "") if ctx.history else ""


def _summary_vi(report: AgentReport) -> str:
    if report.state == "completed":
        return f"Data đã tạo {len(report.artifact_refs)} artifact cho {report.snapshot_id}." + (" Có hạn chế." if report.partial else "")
    code = report.error.code if report.error else report.state
    return f"Data không thực hiện bước này ({report.state}: {code})."


class DataAgent(LiteLLMAgent):
    """Deterministic StepSpec path in front of the legacy LLM loop; `llm=None` serves StepSpec only."""

    def __init__(
        self,
        *,
        llm: LLMClient | None,
        mcp_session_factory: McpSessionFactory = open_mcp_session,
        system_prompt: str,
        compact_prompt: str,
    ) -> None:
        super().__init__(llm=llm, mcp_session_factory=mcp_session_factory,  # pyright: ignore[reportArgumentType]
                         system_prompt=system_prompt, compact_prompt=compact_prompt)
        self._has_llm = llm is not None

    @property
    def has_llm(self) -> bool:
        return self._has_llm

    async def invoke(self, ctx: InvocationContext) -> None:
        try:
            incoming = parse_incoming(_inbound(ctx))
        except ValueError:
            incoming = None  # JSON without `contract`: legacy free text, as before WS2
        if isinstance(incoming, ContractMessage):
            report = await self._contract(ctx, incoming)
            await ctx.emit_assistant(render_agent_report(_summary_vi(report), report))
            return
        if not self._has_llm:
            await ctx.emit_assistant(NO_LLM_TEXT)
            return
        await super().invoke(ctx)

    async def _contract(self, ctx: InvocationContext, message: ContractMessage) -> AgentReport:
        if message.contract != STEPSPEC:
            return rejection("UNSUPPORTED_CONTRACT", f"the data agent accepts {STEPSPEC}, not {message.contract}")
        try:
            step = StepSpec.model_validate(message.data)
        except ValidationError as exc:
            return rejection("INVALID_STEPSPEC", f"not a valid {STEPSPEC}: {exc.error_count()} error(s)")
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            return await run_step(step, SessionTools(mcp))

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        if not self._has_llm:
            return previous_summary  # nothing to fold without a model; the Backend keeps the raw history
        return await super().compact(previous_summary, messages)


def build_agent(env: Mapping[str, str]) -> Agent:
    """Raises `PluginConfigError` naming the missing or invalid setting (unless `DATA_LLM=off`)."""
    if (env.get("DATA_LLM") or "").strip().lower() == "off":
        return DataAgent(llm=None, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"))
    settings = load_settings(env)
    for noisy in ("httpx", "httpx2", "LiteLLM"):  # per-request INFO lines drown out agent logs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    llm = LiteLLMClient(
        model=settings.llm_model,
        api_base=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout_s=settings.llm_timeout_s,
    )
    return DataAgent(llm=llm, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"))
