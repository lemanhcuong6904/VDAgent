"""This agent's brain.

A `StepSpec@1` message (WS2, D4) runs the deterministic real-estate path in `steps.py`: no LLM, one
`AgentReport@1` answer. While it runs, the agent narrates its real work to the person watching, one assistant step per
pipeline phase with the tool calls of that phase (`narrate.py`, `DATA_NARRATE=off` to disable; `DATA_NARRATE_LLM=off`
for template sentences only). The answer, the last step, is unchanged: a closing line and the JSON report.

Free text that the user writes directly (`[from: user]`) is the explanation chat (`chat/`): questions about the package Data
has just fetched, answered from its stored artifacts. It is a branch apart from the pipeline above and never changes it.

Any other message keeps the legacy behaviour, a thin tool-calling loop over LiteLLM
with the Backend's MCP tools: open an MCP session, offer its tools plus `send_to_agent`, and step the model up
to `ctx.max_steps` times (`tool_choice="none"` on the last step). Every assistant step and tool result is
reported through `ctx`; tool calls of one step run concurrently. With `DATA_LLM=off` the plugin loads without
LLM settings and serves StepSpec requests only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from vdagent_contracts.messages import ContractMessage, StepSpec, parse_incoming
from vdagent_contracts.reports import AgentReport, render_agent_report
from vdagent_sdk import SEND_TO_AGENT, Agent, AgentTimeoutError, InvocationContext, Message, Peer, ToolCall

from .chat.loop import ChatLoop
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
from .narrate import LlmNarrator, NarrationStream, Narrator, TemplateNarrator
from .steps import ToolFailure, rejection, run_step
from .wire import Door, Reply, is_v1

NAME = "data"
DESCRIPTION = (
    "Queries the warehouse; returns dataset ids. A StepSpec@1 JSON request (fetch_units, aggregate_metrics) reads the"
    " real-estate DW deterministically and returns dataset/metric/dq artifacts in an AgentReport@1."
)
STEPSPEC = "StepSpec@1"
_SENDER = re.compile(r"^\[from: ([^\]]+)\]")
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


def _sender(text: str) -> str:
    """Who wrote the inbound message: the `[from: <sender>]` the Backend puts in front of it ("user" for a person)."""
    match = _SENDER.match(text)
    return match.group(1) if match else "user"


def _summary_vi(report: AgentReport) -> str:
    if report.state == "completed":
        return f"Data đã tạo {len(report.artifact_refs)} artifact cho {report.snapshot_id}." + (" Có hạn chế." if report.partial else "")
    code = report.error.code if report.error else report.state
    return f"Data không thực hiện bước này ({report.state}: {code})."


def _render_v1(line: str, reply: Reply) -> str:
    return "\n\n".join([line.strip(), f"```json\n{reply.json()}\n```"])


class _CtxSink:
    """Shows a narrated beat as an SDK step: the step first, then the result of each of its tool calls."""

    def __init__(self, ctx: InvocationContext) -> None:
        self._ctx = ctx

    async def step(self, text: str, calls: list[tuple[ToolCall, str]]) -> None:
        await self._ctx.emit_assistant(text, [call for call, _ in calls])
        for call, result in calls:
            await self._ctx.emit_tool_result(call.id, result)


class DataAgent(LiteLLMAgent):
    """Deterministic StepSpec path in front of the legacy LLM loop; `llm=None` serves StepSpec only."""

    def __init__(
        self,
        *,
        llm: LLMClient | None,
        mcp_session_factory: McpSessionFactory = open_mcp_session,
        system_prompt: str,
        compact_prompt: str,
        narrate: bool = True,
        narrate_llm: bool = True,
        narrator_prompt: str | None = None,
        chat_prompt: str | None = None,
        profile: str | None = None,
    ) -> None:
        super().__init__(llm=llm, mcp_session_factory=mcp_session_factory,  # pyright: ignore[reportArgumentType]
                         system_prompt=system_prompt, compact_prompt=compact_prompt)
        self._has_llm = llm is not None
        self._narrate = narrate
        self._narrate_llm = narrate_llm
        self._narrator_prompt = narrator_prompt
        self._chat_prompt = chat_prompt or load_prompt("chat")
        self._profile = profile
        self._door = Door(profile=profile)  # the steps of contract v1.0 seen so far (idempotency, open questions, pins)

    @property
    def has_llm(self) -> bool:
        return self._has_llm

    @property
    def chat_prompt(self) -> str:
        return self._chat_prompt

    @property
    def profile(self) -> str | None:
        """The configured expectation (DATA_DW_PROFILE, None when unset); each step relabels from the serving warehouse."""
        return self._profile

    async def invoke(self, ctx: InvocationContext) -> None:
        if is_v1(_inbound(ctx)):
            await self._contract_v1(ctx, _inbound(ctx))
            return
        try:
            incoming = parse_incoming(_inbound(ctx))
        except ValueError:
            incoming = None  # JSON without `contract`: legacy free text, as before WS2
        if isinstance(incoming, ContractMessage):
            report, closing = await self._contract(ctx, incoming)
            await ctx.emit_assistant(render_agent_report(closing or _summary_vi(report), report))
            return
        if not self._has_llm:
            await ctx.emit_assistant(NO_LLM_TEXT)
            return
        if _sender(_inbound(ctx)) == "user":
            await self._chat(ctx)
            return
        await super().invoke(ctx)

    async def _chat(self, ctx: InvocationContext) -> None:
        """A question the user wrote about the package Data has just fetched: answered from its stored artifacts."""
        loop = ChatLoop(self._llm, system_prompt=self._chat_prompt)
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            answer = await loop.reply(ctx.history, SessionTools(mcp), _CtxSink(ctx))
        await ctx.emit_assistant(answer)

    def _narrator(self) -> Narrator:
        template = TemplateNarrator()
        if self._narrate_llm and self._has_llm:
            return LlmNarrator(self._llm, template, system_prompt=self._narrator_prompt or load_prompt("narrator"))
        return template

    async def _contract_v1(self, ctx: InvocationContext, text: str) -> None:
        """A message of the Orchestrator contract v1.0: the work is narrated, the answer is the contract's reply."""
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            tools = SessionTools(mcp)
            closing = ""
            if not self._narrate:
                reply = await self._door.handle(text, tools)
            else:
                stream = NarrationStream(self._narrator(), _CtxSink(ctx))
                try:
                    reply = await self._door.handle(text, tools, observer=stream)
                    closing = await stream.close()
                finally:
                    await stream.abort()
        await ctx.emit_assistant(_render_v1(closing or reply.text, reply))

    async def _contract(self, ctx: InvocationContext, message: ContractMessage) -> tuple[AgentReport, str]:
        """The report and, when narrating, the closing line of the narration (`""` otherwise)."""
        if message.contract != STEPSPEC:
            return rejection("UNSUPPORTED_CONTRACT", f"the data agent accepts {STEPSPEC}, not {message.contract}"), ""
        try:
            step = StepSpec.model_validate(message.data)
        except ValidationError as exc:
            return rejection("INVALID_STEPSPEC", f"not a valid {STEPSPEC}: {exc.error_count()} error(s)"), ""
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            tools = SessionTools(mcp)
            if not self._narrate:
                return await run_step(step, tools, profile=self._profile), ""
            stream = NarrationStream(self._narrator(), _CtxSink(ctx))
            try:
                report = await run_step(step, tools, observer=stream, profile=self._profile)
                return report, await stream.close()
            finally:
                await stream.abort()

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        if not self._has_llm:
            return previous_summary  # nothing to fold without a model; the Backend keeps the raw history
        return await super().compact(previous_summary, messages)


def _on(env: Mapping[str, str], name: str) -> bool:
    """A switch that is on unless it says `off`."""
    return (env.get(name) or "").strip().lower() != "off"


def build_agent(env: Mapping[str, str]) -> Agent:
    """Raises `PluginConfigError` naming the missing or invalid setting (unless `DATA_LLM=off`).

    `DATA_NARRATE=off` turns the narration of StepSpec turns off (one answer step, as before);
    `DATA_NARRATE_LLM=off` keeps the narration but never sends it to the LLM.
    `DATA_DW_PROFILE` (optional) is only an expectation: the labels follow the warehouse the Backend reports serving
    (PostgreSQL → real: no "synthetic" labels, snapshot approval assumed and said so; SQLite → the synthetic mock).
    """
    narration = {"narrate": _on(env, "DATA_NARRATE"), "narrate_llm": _on(env, "DATA_NARRATE_LLM"),
                 "profile": (env.get("DATA_DW_PROFILE") or "").strip().lower() or None}
    if (env.get("DATA_LLM") or "").strip().lower() == "off":
        return DataAgent(llm=None, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"), **narration)
    settings = load_settings(env)
    for noisy in ("httpx", "httpx2", "LiteLLM"):  # per-request INFO lines drown out agent logs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    llm = LiteLLMClient(
        model=settings.llm_model,
        api_base=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout_s=settings.llm_timeout_s,
    )
    return DataAgent(llm=llm, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"), **narration)
