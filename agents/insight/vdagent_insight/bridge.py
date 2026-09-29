"""`CtxBridge`: maps LangChain's agent loop onto the vdagent turn contract.

- every model call: at most `ctx.max_steps` of them get tools (the step budget); the last is
  tool-free, and a model that still asks for tools gets `STEP_LIMIT_TEXT` instead, so the turn
  ends with an answer. Missing tool-call ids are filled in (the contract needs unique ones). A
  timeout becomes `AgentTimeoutError`.
- after every model call: `ctx.emit_assistant`, before any of its tool calls run.
- every tool call: `send_to_agent` goes through `ctx.call_agent`; failures become `error: …`
  content so the turn continues; the result is reported with `ctx.emit_tool_result`.

One instance per turn: it counts that turn's steps.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

import openai
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from vdagent_sdk import SEND_TO_AGENT, AgentTimeoutError, InvocationContext, ToolCall

STEP_LIMIT_TEXT = "[step limit reached before I could finish; no further tool calls were made]"


def _with_ids(message: AIMessage) -> AIMessage:
    if all(tc.get("id") for tc in message.tool_calls):
        return message
    calls = [{**tc, "id": tc.get("id") or f"call_{secrets.token_hex(8)}"} for tc in message.tool_calls]
    return message.model_copy(update={"tool_calls": calls})


class CtxBridge(AgentMiddleware):
    def __init__(self, ctx: InvocationContext, timeout_s: float) -> None:
        super().__init__()
        self._ctx = ctx
        self._timeout_s = timeout_s
        self._steps = 0

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        self._steps += 1
        last = self._steps >= self._ctx.max_steps
        if last:
            request = request.override(tools=[])
        try:
            async with asyncio.timeout(self._timeout_s):
                response = await handler(request)
        except (TimeoutError, openai.APITimeoutError) as exc:
            raise AgentTimeoutError(f"model call timed out after {self._timeout_s:g}s") from exc
        result = [_with_ids(m) if isinstance(m, AIMessage) else m for m in response.result]
        if last:
            result = [
                AIMessage(content=m.text or STEP_LIMIT_TEXT, id=m.id) if isinstance(m, AIMessage) and m.tool_calls else m
                for m in result
            ]
        return ModelResponse(result=result, structured_response=response.structured_response)

    async def aafter_model(self, state: Any, runtime: Any) -> None:
        message = state["messages"][-1]
        calls = [ToolCall(tc["id"], tc["name"], json.dumps(tc["args"])) for tc in message.tool_calls]
        await self._ctx.emit_assistant(message.text, calls)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> ToolMessage:
        call = request.tool_call
        content = await self._content(request, handler)
        await self._ctx.emit_tool_result(call["id"], content)
        return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"])

    async def _content(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> str:
        name, args = request.tool_call["name"], request.tool_call["args"]
        if name == SEND_TO_AGENT and self._ctx.peers:
            target, message = args.get("agent"), args.get("message")
            if not isinstance(target, str) or not target.strip():
                return "error: send_to_agent requires 'agent' (the name of the agent to call)"
            if not isinstance(message, str) or not message.strip():
                return "error: send_to_agent requires a non-empty 'message'"
            return await self._ctx.call_agent(request.tool_call["id"], target.strip(), message)
        if request.tool is None:
            return f"error: unknown tool '{name}'"
        try:
            result = await handler(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return f"error: tool '{name}' failed: {exc}"
        return result.text if isinstance(result, ToolMessage) else str(result)
