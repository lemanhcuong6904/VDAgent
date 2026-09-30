"""This agent's brain.

Every analysis runs the code-enforced DAG (dag.py → executor.py → answer.py): Data → [Insight ∥ Compare] → Chart
→ Report through the Backend's own agent calls. The plan comes from a structured `AnalysisRequest@1` (planner.py),
from the deterministic classifier (`ORCH_LLM=off`), or from the LLM planner (llm_planner.py, `ORCH_LLM=on`), whose
output is validated and compiled by code before it runs. The legacy tool-calling loop below (LiteLLM with the
Backend's MCP tools) runs only with `ORCH_LEGACY_LOOP=on`, a debug switch outside the DAG.

Per turn: open an MCP session, offer its tools plus `send_to_agent`, and step the model up to
`ctx.max_steps` times (`tool_choice="none"` on the last step). Every assistant step and tool
result is reported through `ctx`; tool calls of one step run concurrently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from vdagent_agentkit.mcp_client import JsonTools
from vdagent_contracts.messages import ContractMessage, parse_incoming
from vdagent_sdk import SEND_TO_AGENT, Agent, AgentTimeoutError, InvocationContext, Message, Peer, ToolCall

from .llm import AssistantMessage, LiteLLMClient, LLMClient, LLMTimeoutError, ToolChoice
from .mcp_client import McpSession, McpSessionFactory, open_mcp_session, openai_tool_schema, run_mcp_tool
from .answer import report_outcome, run_and_answer
from .dag import Plan, PlanError
from .llm_planner import plan_with_llm
from .planner import AnalysisRequest, build_plan, classify, parse_request
from .settings import load_settings

log = logging.getLogger(__name__)

NAME = "orchestrator"
DESCRIPTION = "Talks to the user, plans, delegates, writes final answers."

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


NO_LLM_TEXT = (
    "Orchestrator đang chạy không có LLM (ORCH_LLM=off): chỉ nhận câu hỏi về một căn cụ thể (mã căn như A12-08,"
    " kèm 'vì sao' / 'so sánh' / 'biểu đồ') hoặc yêu cầu AnalysisRequest@1. Câu hỏi khác cần cấu hình LLM."
)


OUT_OF_SCOPE_TEXT = (
    "Orchestrator chỉ phân tích một căn cụ thể (mã căn như A12-08): vì sao bán chậm, so sánh với căn tương đồng,"
    " biểu đồ, báo cáo. Câu hỏi này nằm ngoài phạm vi đó nên không có phân tích nào được chạy."
)


def _strip_sender(text: str) -> str:
    """The engine prefixes inbound text with `[from: user] `; the planner sees only the user's words."""
    return re.sub(r"^\[from: [^\]]+\]\s*", "", text)


class OrchestratorAgent(LiteLLMAgent):
    """The DAG path in front of the legacy LLM loop; `llm=None` serves the DAG only."""

    def __init__(self, *, llm: LLMClient | None, mcp_session_factory: McpSessionFactory = open_mcp_session,
                 system_prompt: str, compact_prompt: str, snapshot_id: str | None = None,
                 semantic_config_version: str | None = None, dag_timeout_s: float = 300.0,
                 legacy_loop: bool = False) -> None:
        super().__init__(llm=llm, mcp_session_factory=mcp_session_factory,  # pyright: ignore[reportArgumentType]
                         system_prompt=system_prompt, compact_prompt=compact_prompt)
        self._has_llm = llm is not None
        self._legacy_loop = legacy_loop and llm is not None
        self._snapshot_id, self._semantic = snapshot_id, semantic_config_version
        self._dag_timeout_s = dag_timeout_s

    @property
    def has_llm(self) -> bool:
        return self._has_llm

    @property
    def legacy_loop(self) -> bool:
        return self._legacy_loop

    async def invoke(self, ctx: InvocationContext) -> None:
        text = str(ctx.history[-1].get("content") or "") if ctx.history else ""
        try:
            incoming = parse_incoming(text)
        except ValueError:
            incoming = None
        if isinstance(incoming, ContractMessage):
            if incoming.contract != "AnalysisRequest@1":
                report_outcome(ctx, "failed")
                await ctx.emit_assistant(f"Không hoàn thành: orchestrator nhận AnalysisRequest@1, không nhận {incoming.contract}.")
                return
            try:
                request = parse_request(incoming.data)
            except PlanError as exc:
                report_outcome(ctx, "failed")
                await ctx.emit_assistant(f"Không hoàn thành: {exc.code} — {exc.message}")
                return
            await self._run_dag(ctx, request)
            return
        question = incoming.text if incoming is not None else text
        if self._legacy_loop:
            await super().invoke(ctx)  # ORCH_LEGACY_LOOP=on only: the old tool loop, outside the DAG (debug)
            return
        if self._has_llm:
            await self._run_llm_plan(ctx, _strip_sender(question))
            return
        request = classify(question, snapshot_id=self._snapshot_id, semantic_config_version=self._semantic)
        if request is None:
            await ctx.emit_assistant(NO_LLM_TEXT)
            return
        await self._run_dag(ctx, request)

    async def _run_llm_plan(self, ctx: InvocationContext, question: str) -> None:
        """ORCH_LLM=on: the LLM proposes the plan, code validates and compiles it, the same executor runs it."""
        try:
            plan, _ = await plan_with_llm(self._llm, question, run_id=ctx.task_id, snapshot_id=self._snapshot_id,
                                          semantic_config_version=self._semantic)
        except LLMTimeoutError as exc:
            report_outcome(ctx, "failed")
            await ctx.emit_assistant(f"Không hoàn thành: LLM_PLAN_UNAVAILABLE — {exc}")
            return
        except PlanError as exc:
            if exc.code == "OUT_OF_SCOPE":
                await ctx.emit_assistant(OUT_OF_SCOPE_TEXT)
                return
            report_outcome(ctx, "failed")
            await ctx.emit_assistant(f"Không hoàn thành: {exc.code} — {exc.message}")
            return
        await self._execute(ctx, plan)

    async def _run_dag(self, ctx: InvocationContext, request: AnalysisRequest) -> None:
        try:
            plan = build_plan(request, ctx.task_id)
        except PlanError as exc:
            report_outcome(ctx, "failed")
            await ctx.emit_assistant(f"Không hoàn thành: {exc.code} — {exc.message}")
            return
        await self._execute(ctx, plan)

    async def _execute(self, ctx: InvocationContext, plan: Plan) -> None:
        async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
            await run_and_answer(ctx, JsonTools(mcp), plan, timeout_s=self._dag_timeout_s)

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        if not self._has_llm:
            return previous_summary
        return await super().compact(previous_summary, messages)


def build_agent(env: Mapping[str, str]) -> Agent:
    """Raises `PluginConfigError` naming the missing or invalid setting (unless `ORCH_LLM=off`).

    `ORCH_SNAPSHOT_ID` / `ORCH_SEMANTIC_VERSION` pin the snapshot of free-text DAG runs explicitly (no default and
    no "latest"); `ORCH_DAG_TIMEOUT_S` bounds a whole run (default 300 s).
    """
    snapshot = (env.get("ORCH_SNAPSHOT_ID") or "").strip() or None
    semantic = (env.get("ORCH_SEMANTIC_VERSION") or "").strip() or None
    timeout = float(env.get("ORCH_DAG_TIMEOUT_S") or 300)
    if (env.get("ORCH_LLM") or "").strip().lower() == "off":
        log.info("orchestrator: deterministic planner (ORCH_LLM=off), snapshot %s, semantic %s", snapshot, semantic)
        return OrchestratorAgent(llm=None, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"),
                                 snapshot_id=snapshot, semantic_config_version=semantic, dag_timeout_s=timeout)
    settings = load_settings(env)
    for noisy in ("httpx", "httpx2", "LiteLLM"):  # per-request INFO lines drown out agent logs
        logging.getLogger(noisy).setLevel(logging.WARNING)
    llm = LiteLLMClient(
        model=settings.llm_model,
        api_base=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout_s=settings.llm_timeout_s,
    )
    legacy = (env.get("ORCH_LEGACY_LOOP") or "").strip().lower() == "on"
    log.info("orchestrator: %s (model %s), snapshot %s, semantic %s",
             "LEGACY tool loop (ORCH_LEGACY_LOOP=on)" if legacy else "LLM planner on", settings.llm_model, snapshot, semantic)
    return OrchestratorAgent(llm=llm, system_prompt=load_prompt("system"), compact_prompt=load_prompt("compact"),
                             snapshot_id=snapshot, semantic_config_version=semantic, dag_timeout_s=timeout,
                             legacy_loop=legacy)
