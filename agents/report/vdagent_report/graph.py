"""One turn as a hand-built LangGraph `StateGraph`:

    agent ──tool calls──▶ tools ──▶ agent
    agent ──text draft──▶ assess ──pass──▶ finalize
                          assess ──reject, budget left──▶ revise ──▶ agent   (at most once)
                          assess ──reject, no budget──▶ finalize

Tool-call steps and their results are emitted as they happen. A text reply is only a *draft*: Jev judges it
(judge.py) and only the draft that leaves `assess` is emitted, by `finalize`. The Backend never
sees a rejected draft or the review.
"""

from __future__ import annotations

import asyncio
import json
import operator
import re
import secrets
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from vdagent_contracts.reports import AgentReport, ReportError, render_agent_report
from vdagent_sdk import SEND_TO_AGENT, AgentTimeoutError, InvocationContext, ToolCall

from .judge import Judge, Verdict
from .mcp_client import McpSession, run_mcp_tool

STEP_LIMIT_TEXT = "[step limit reached before I could finish; no further tool calls were made]"
ARTIFACT_ID = re.compile(r"\b(?:ds|ch|rp|art)_\w+")
CONTEXT_ID_RE = re.compile(r"\b(?:ds|ch|rp|art)[_-][A-Za-z0-9_-]+|\bART-[A-Za-z0-9_-]+", re.IGNORECASE)
ALLOWED_DIRECT_CHAT_TOOLS = frozenset({"describe_dataset", "get_dataset_rows", "artifact_get"})


def extract_context_ids(
    history: Sequence[Any],
    summary: str = "",
    extra_ids: Sequence[str] = (),
) -> set[str]:
    sources: list[str] = [summary]
    for msg in history:
        if isinstance(msg, BaseMessage):
            if msg.type in {"human", "tool"} and msg.content:
                sources.append(str(msg.content))
        elif isinstance(msg, dict):
            if msg.get("role") in {"user", "tool"} and msg.get("content"):
                sources.append(str(msg["content"]))
    combined = " ".join(sources)
    found = set(CONTEXT_ID_RE.findall(combined))
    for pat in (
        r'["\'](?:dataset_id|artifact_id)["\']\s*:\s*["\']([^"\']+)["\']',
        r'\b(?:dataset|artifact)\s+["\']?([a-zA-Z0-9_-]+)["\']?',
    ):
        found.update(re.findall(pat, combined, re.IGNORECASE))
    found.update(extra_ids)
    return {i.strip() for i in found if i.strip()}


class TurnState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], operator.add]
    steps: int
    revisions: int
    draft: str
    artifacts: Annotated[list[str], operator.add]
    verdict: Verdict


def _with_ids(message: AIMessage) -> AIMessage:
    if all(tc.get("id") for tc in message.tool_calls):
        return message
    calls = [{**tc, "id": tc.get("id") or f"call_{secrets.token_hex(8)}"} for tc in message.tool_calls]
    return message.model_copy(update={"tool_calls": calls})


def _verdict(state: TurnState) -> Verdict:
    verdict = state.get("verdict")
    assert verdict is not None, "assess runs before any edge that reads the verdict"
    return verdict


class ReportTurn:
    """The nodes of one turn; `graph()` wires them. Per-turn state lives in the graph state."""

    def __init__(
        self,
        *,
        ctx: InvocationContext,
        mcp: McpSession,
        model: BaseChatModel,
        tools: Sequence[dict[str, Any]],
        mcp_tool_names: set[str],
        judge: Judge,
        system_prompt: str,
        timeout_s: float,
        direct_chat: bool = False,
    ) -> None:
        self._ctx = ctx
        self._mcp = mcp
        self._model = model
        self._tools = list(tools)
        self._mcp_tool_names = mcp_tool_names
        self._judge = judge
        self._system_prompt = system_prompt
        self._timeout_s = timeout_s
        self._direct_chat = direct_chat

    def graph(self) -> CompiledStateGraph:
        g = StateGraph(TurnState)
        g.add_node("agent", self.agent)
        g.add_node("tools", self.tools)
        g.add_node("assess", self.assess)
        g.add_node("revise", self.revise)
        g.add_node("finalize", self.finalize)
        g.add_edge(START, "agent")
        g.add_conditional_edges("agent", self.after_agent, ["tools", "assess"])
        g.add_edge("tools", "agent")
        g.add_conditional_edges("assess", self.after_assess, ["revise", "finalize"])
        g.add_edge("revise", "agent")
        g.add_edge("finalize", END)
        return g.compile()

    # ---------------------------------------------------------------- nodes

    async def agent(self, state: TurnState) -> dict[str, Any]:
        steps = state.get("steps", 0) + 1
        last = steps >= self._ctx.max_steps
        model = self._model if last or not self._tools else self._model.bind_tools(self._tools)
        prompt = [SystemMessage(self._system_prompt), *state.get("messages", [])]
        try:
            async with asyncio.timeout(self._timeout_s):
                reply = await model.ainvoke(prompt)
        except (TimeoutError, openai.APITimeoutError) as exc:
            raise AgentTimeoutError(f"model call timed out after {self._timeout_s:g}s") from exc
        reply = _with_ids(reply) if isinstance(reply, AIMessage) else AIMessage(content=str(reply.content))
        if last and reply.tool_calls:
            reply = AIMessage(content=reply.text or STEP_LIMIT_TEXT)
        if reply.tool_calls:
            calls = [ToolCall(str(tc["id"]), tc["name"], json.dumps(tc["args"])) for tc in reply.tool_calls]
            await self._ctx.emit_assistant(reply.text, calls)
            return {"steps": steps, "messages": [reply], "draft": ""}
        return {"steps": steps, "draft": reply.text}

    def after_agent(self, state: TurnState) -> str:
        return "assess" if state.get("draft") or not self._pending_calls(state) else "tools"

    async def tools(self, state: TurnState) -> dict[str, Any]:
        calls = self._pending_calls(state)
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self._run_tool_call(tc, state)) for tc in calls]
        contents = [t.result() for t in tasks]
        found = [i for c in contents for i in ARTIFACT_ID.findall(c) if i not in state.get("artifacts", [])]
        return {
            "messages": [ToolMessage(content=c, tool_call_id=tc["id"], name=tc["name"]) for tc, c in zip(calls, contents, strict=True)],
            "artifacts": list(dict.fromkeys(found)),
        }

    async def assess(self, state: TurnState) -> dict[str, Any]:
        request = str(self._ctx.history[-1]["content"])
        if self._direct_chat:
            assess_direct = getattr(self._judge, "assess_direct", None)
            if callable(assess_direct):
                verdict = await assess_direct(request, state.get("draft", ""), state.get("artifacts", []))
                return {"verdict": verdict}
        return {"verdict": await self._judge.assess(request, state.get("draft", ""), state.get("artifacts", []))}

    def after_assess(self, state: TurnState) -> str:
        if _verdict(state).passed:
            return "finalize"
        if state.get("revisions", 0) == 0 and state.get("steps", 0) < self._ctx.max_steps:
            return "revise"
        return "finalize"

    async def revise(self, state: TurnState) -> dict[str, Any]:
        verdict = _verdict(state)
        review_text = verdict.direct_chat_review if self._direct_chat else verdict.review
        review = HumanMessage(f"[reviewer] {review_text}")
        draft = AIMessage(content=state.get("draft", ""))
        return {"messages": [draft, review], "revisions": state.get("revisions", 0) + 1, "draft": ""}

    async def finalize(self, state: TurnState) -> dict[str, Any]:
        draft = state.get("draft", "")
        if self._direct_chat:
            verdict = state.get("verdict")
            rejected = verdict is not None and not verdict.passed
            gate_unavailable = verdict is not None and verdict.acceptable is None
            partial = STEP_LIMIT_TEXT in draft or rejected or gate_unavailable
            warnings: list[str] = []
            if STEP_LIMIT_TEXT in draft:
                warnings.append("STEP_LIMIT_REACHED")
            if verdict is not None and not verdict.passed:
                warnings.append(f"QUALITY_GATE_REJECTED:{verdict.problem or 'unspecified'}")
            elif gate_unavailable:
                warnings.append("QUALITY_GATE_UNAVAILABLE")

            summary = draft.strip()
            if STEP_LIMIT_TEXT in summary:
                summary = "Chưa thể hoàn tất giải đáp trong giới hạn số bước của lượt này."
            elif not summary:
                summary = "Report chưa tạo được nội dung trả lời trong lượt này."

            output_summary = (
                "Chưa thể gửi câu trả lời vì nội dung chưa vượt qua kiểm tra chất lượng."
                if rejected
                else summary
            )
            summary_lines = [
                line.strip() for line in output_summary.splitlines() if line.strip() and not line.strip().startswith("#")
            ]
            head = "\n".join(summary_lines[:2]) if summary_lines else "Giải đáp từ Report Agent:"
            # `parse_agent_report` expects exactly one JSON fence. A draft may contain a fenced
            # example in its first lines, so keep the human-readable preface from opening a
            # second envelope (the full draft remains intact in the JSON summary field).
            head = head.replace("```", "'''")
            if len(head) > 200:
                head = head[:197] + "..."

            report = AgentReport(
                state="rejected" if rejected else "completed",
                summary=output_summary,
                artifact_refs=[],
                partial=partial,
                warnings=warnings,
                error=(
                    ReportError(
                        code="QUALITY_GATE_REJECTED",
                        message="The final direct-chat draft did not pass the quality gate after its allowed revision.",
                    )
                    if rejected
                    else None
                ),
            )
            output = render_agent_report(head, report)
            await self._ctx.emit_assistant(output)
        else:
            await self._ctx.emit_assistant(draft)
        return {}

    # ---------------------------------------------------------------- tools

    @staticmethod
    def _pending_calls(state: TurnState) -> list[dict[str, Any]]:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        return [dict(tc) for tc in last.tool_calls] if isinstance(last, AIMessage) else []

    async def _run_tool_call(self, tc: dict[str, Any], state: TurnState | None = None) -> str:
        content = await self._tool_content(tc["id"], tc["name"], tc["args"], state)
        await self._ctx.emit_tool_result(tc["id"], content)
        return content

    async def _tool_content(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict[str, Any],
        state: TurnState | None = None,
    ) -> str:
        if self._direct_chat:
            if name not in ALLOWED_DIRECT_CHAT_TOOLS:
                return f"error: tool '{name}' is not permitted in direct chat mode"

            allowed_ids = extract_context_ids(
                self._ctx.history,
                self._ctx.summary,
                extra_ids=state.get("artifacts", []) if state else [],
            )

            if name == "artifact_get":
                art_id = arguments.get("artifact_id")
                if not art_id or str(art_id) not in allowed_ids:
                    return (
                        f"error: artifact_get is restricted to artifact ids present in context"
                        f" ('{art_id}' not found in context)"
                    )
            elif name in ("describe_dataset", "get_dataset_rows"):
                ds_id = arguments.get("dataset_id")
                if not ds_id or str(ds_id) not in allowed_ids:
                    return (
                        f"error: {name} is restricted to dataset ids present in context"
                        f" ('{ds_id}' not found in context)"
                    )

        if name == SEND_TO_AGENT and self._ctx.peers:
            if self._direct_chat:
                return "error: send_to_agent is not permitted in direct chat mode"
            target, message = arguments.get("agent"), arguments.get("message")
            if not isinstance(target, str) or not target.strip():
                return "error: send_to_agent requires 'agent' (the name of the agent to call)"
            if not isinstance(message, str) or not message.strip():
                return "error: send_to_agent requires a non-empty 'message'"
            return await self._ctx.call_agent(tool_call_id, target.strip(), message)
        if name in self._mcp_tool_names:
            return await run_mcp_tool(self._mcp, name, arguments)
        return f"error: unknown tool '{name}'"
