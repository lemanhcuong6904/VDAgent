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
from vdagent_sdk import SEND_TO_AGENT, AgentTimeoutError, InvocationContext, ToolCall

from .judge import Judge, Verdict
from .mcp_client import McpSession, run_mcp_tool

STEP_LIMIT_TEXT = "[step limit reached before I could finish; no further tool calls were made]"
ARTIFACT_ID = re.compile(r"\b(?:ds|ch|rp)_\w+")


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
    ) -> None:
        self._ctx = ctx
        self._mcp = mcp
        self._model = model
        self._tools = list(tools)
        self._mcp_tool_names = mcp_tool_names
        self._judge = judge
        self._system_prompt = system_prompt
        self._timeout_s = timeout_s

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
            tasks = [tg.create_task(self._run_tool_call(tc)) for tc in calls]
        contents = [t.result() for t in tasks]
        found = [i for c in contents for i in ARTIFACT_ID.findall(c) if i not in state.get("artifacts", [])]
        return {
            "messages": [ToolMessage(content=c, tool_call_id=tc["id"], name=tc["name"]) for tc, c in zip(calls, contents, strict=True)],
            "artifacts": list(dict.fromkeys(found)),
        }

    async def assess(self, state: TurnState) -> dict[str, Any]:
        request = str(self._ctx.history[-1]["content"])
        return {"verdict": await self._judge.assess(request, state.get("draft", ""), state.get("artifacts", []))}

    def after_assess(self, state: TurnState) -> str:
        if _verdict(state).passed:
            return "finalize"
        if state.get("revisions", 0) == 0 and state.get("steps", 0) < self._ctx.max_steps:
            return "revise"
        return "finalize"

    async def revise(self, state: TurnState) -> dict[str, Any]:
        review = HumanMessage(f"[reviewer] {_verdict(state).review}")
        draft = AIMessage(content=state.get("draft", ""))
        return {"messages": [draft, review], "revisions": state.get("revisions", 0) + 1, "draft": ""}

    async def finalize(self, state: TurnState) -> dict[str, Any]:
        await self._ctx.emit_assistant(state.get("draft", ""))
        return {}

    # ---------------------------------------------------------------- tools

    @staticmethod
    def _pending_calls(state: TurnState) -> list[dict[str, Any]]:
        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        return [dict(tc) for tc in last.tool_calls] if isinstance(last, AIMessage) else []

    async def _run_tool_call(self, tc: dict[str, Any]) -> str:
        content = await self._tool_content(tc["id"], tc["name"], tc["args"])
        await self._ctx.emit_tool_result(tc["id"], content)
        return content

    async def _tool_content(self, tool_call_id: str, name: str, arguments: dict[str, Any]) -> str:
        if name == SEND_TO_AGENT and self._ctx.peers:
            target, message = arguments.get("agent"), arguments.get("message")
            if not isinstance(target, str) or not target.strip():
                return "error: send_to_agent requires 'agent' (the name of the agent to call)"
            if not isinstance(message, str) or not message.strip():
                return "error: send_to_agent requires a non-empty 'message'"
            return await self._ctx.call_agent(tool_call_id, target.strip(), message)
        if name in self._mcp_tool_names:
            return await run_mcp_tool(self._mcp, name, arguments)
        return f"error: unknown tool '{name}'"
