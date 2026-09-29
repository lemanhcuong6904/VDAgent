"""The Compare agent: the model plans and phrases, the deterministic engine owns every number.

One turn (spec §1.9, §2.1):
1. Understand: a JSON request from another agent is used as is; otherwise the model fills a
   `ComparisonPlan` (checked by `planner.plan_to_request`), and the rule parser takes over when
   the model is absent, down, or proposes something invalid.
2. Compute: `CompareService.run` in a worker thread, reported as a `run_comparison` tool step so
   the evidence (status, data level, artifact ids) is visible in the task log.
3. Answer: a model-written summary that passed `phrasing.check_phrase`, then the engine's own
   tables. LIMITED answers open with their limits (spec §2.4). Without a usable model the
   template text alone is the answer, with every number.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from typing import TypeVar

from vdagent_sdk import InvocationContext, Message, ToolCall

from . import phrasing, planner
from .llm import JsonLLM, LLMUnavailableError
from .vh_chat import HELP, parse_request, render
from .vh_service import CompareService

log = logging.getLogger(__name__)

NAME = "compare"
DESCRIPTION = ("So sánh căn hộ / phân khu / dự án: nhóm căn tương đồng, so trực diện, theo nhóm, xếp hạng. "
               "Mọi con số do engine tất định tính; không giải thích nguyên nhân.")
OUT_OF_SCOPE = ("Compare chỉ so sánh căn hộ, phân khu hoặc dự án (nhóm tương đồng, so trực diện, theo nhóm, "
                "xếp hạng). " + HELP)
PACK_MISSING = ("Chưa có gói dữ liệu VHOP trên máy chủ này nên chưa so được căn thật. Gói do team DATA phát hành; "
                "đặt vào warehouse/vhop (hoặc đặt biến VDAGENT_VHOP_DATA_DIR). Câu hỏi về căn mẫu A12-08 vẫn trả lời được.")
MODEL_DOWN_NOTE ="_(Lượt này không dùng được mô hình ngôn ngữ; câu trả lời theo mẫu, số liệu vẫn đủ.)_"
TURN_BUDGET_S = 25.0  # step deadline is 30 s (spec §3.4); leave room for the engine and the Backend
_SENDER = re.compile(r"^\[from: [^\]]*\]\s*")
T = TypeVar("T")


def _text(message: Message) -> str:
    return _SENDER.sub("", str(message.get("content") or ""), count=1).strip()


def _earlier(history: list[Message]) -> list[str]:
    """Earlier turns, shortened, so the planner can resolve follow-up questions."""
    lines = []
    for message in history[:-1]:
        if message.get("role") == "user":
            lines.append("Người dùng: " + _text(message)[:300])
        elif message.get("role") == "assistant" and message.get("content"):
            lines.append("Compare: " + str(message["content"]).split("\n", 1)[0][:300])
    return lines


def _evidence(result: dict) -> str:
    cmp = result["comparison"]
    return json.dumps({
        "status": cmp["status"], "reason_code": cmp.get("reason_code"),
        "comparisonMode": cmp.get("comparisonMode"), "confidence": cmp.get("confidence"),
        "dataSufficiency": {k: v for k, v in (cmp.get("dataSufficiency") or {}).items() if k != "perMetric"} or None,
        "artifact_id": cmp["artifact_id"], "content_hash": cmp["content_hash"],
        "peer_definition_id": (result.get("peer_definition") or {}).get("artifact_id"),
    }, ensure_ascii=False)


class CompareAgent:
    """One instance serves concurrent turns (SDK R8): per-turn state stays in `_Turn`."""

    def __init__(self, *, llm: JsonLLM | None = None, service: CompareService | None = None) -> None:
        self._llm = llm
        self._service = service or CompareService()

    @property
    def has_model(self) -> bool:
        return self._llm is not None

    @property
    def model_names(self) -> tuple[str, ...]:
        return tuple(getattr(self._llm, "models", ()))

    async def invoke(self, ctx: InvocationContext) -> None:
        await _Turn(ctx, self._llm, self._service).run()

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        """Keep the questions (they carry the entity codes follow-ups refer to); drop the tables."""
        asked = [_text(m)[:200] for m in messages if m.get("role") == "user"]
        lines = [line for line in [previous_summary.strip(), *(f"- Đã hỏi: {q}" for q in asked)] if line]
        return "\n".join(lines)[-2_000:]


class _Turn:
    def __init__(self, ctx: InvocationContext, llm: JsonLLM | None, service: CompareService) -> None:
        self._ctx = ctx
        self._llm = llm
        self._service = service
        self._deadline = asyncio.get_running_loop().time() + TURN_BUDGET_S
        self._model_failed = False

    async def run(self) -> None:
        ctx = self._ctx
        question = _text(ctx.history[-1]) if ctx.history else ""
        request, reply = await self._understand(question, _earlier(ctx.history))
        if request is None:
            await ctx.emit_assistant(reply)
            return
        call = None
        if ctx.max_steps >= 2:
            call = ToolCall(id=f"call_{secrets.token_hex(6)}", name="run_comparison",
                            arguments_json=json.dumps(request, ensure_ascii=False))
            await ctx.emit_assistant("", [call])
        try:
            result = await asyncio.to_thread(self._service.run, request)
        except FileNotFoundError as exc:  # the DATA team's pack is not on this server
            await self._fail(call, "DATA_PACK_MISSING", str(exc), PACK_MISSING)
            return
        except (KeyError, TypeError, ValueError) as exc:  # a request shape the engine's checks missed
            await self._fail(call, "INVALID_INPUT", str(exc), f"Yêu cầu chưa hợp lệ: {exc}. {HELP}")
            return
        if call is not None:
            await ctx.emit_tool_result(call.id, _evidence(result))
        structured = question.startswith("{")  # another agent: it reads the tables, no wording needed
        await ctx.emit_assistant(render(result) if structured else await self._answer(question, result))

    async def _fail(self, call: ToolCall | None, code: str, reason: str, reply: str) -> None:
        if call is not None:  # SDK R3: every tool call gets exactly one result
            await self._ctx.emit_tool_result(call.id, json.dumps(
                {"status": "ERROR", "reason_code": code, "reason": reason}, ensure_ascii=False))
        await self._ctx.emit_assistant(reply)

    async def _model(self, make: Callable[[], Awaitable[T]]) -> T | None:
        """A model call within the turn budget; any failure is logged and becomes `None`."""
        remaining = self._deadline - asyncio.get_running_loop().time()
        if self._llm is None or remaining <= 1:
            return None
        try:
            async with asyncio.timeout(remaining):
                return await make()
        except (LLMUnavailableError, TimeoutError, KeyError, TypeError, AttributeError, ValueError) as exc:
            # unreachable model, or a reply outside the schema (plain JSON mode): rules/templates take over
            log.warning("compare: model unusable this turn, using rules/templates: %r", exc)
            self._model_failed = True
            return None

    async def _understand(self, question: str, earlier: list[str]) -> tuple[dict | None, str]:
        if question.startswith("{"):  # structured request from another agent or a test harness
            request = parse_request(question)
            return (request, "") if request else (None, "Yêu cầu JSON không hợp lệ. " + HELP)
        llm = self._llm
        plan = await self._model(lambda: planner.plan(llm, question, earlier)) if llm else None
        if plan is not None:
            if plan.kind == "request":
                return plan.request, ""
            if plan.kind == "clarify":
                return None, plan.message
            if plan.kind == "out_of_scope":
                return None, OUT_OF_SCOPE
            log.info("compare: plan rejected (%s); falling back to rules", plan.message)
        request = parse_request(question)
        return (request, "") if request else (None, HELP)

    async def _answer(self, question: str, result: dict) -> str:
        rendered = render(result)
        cmp = result["comparison"]
        if cmp["status"] == "INVALID" or cmp.get("clarification"):
            return rendered
        llm = self._llm
        facts = phrasing.facts_from(rendered)
        text = await self._model(lambda: phrasing.phrase(llm, question, facts)) if llm else None
        sufficiency = cmp.get("dataSufficiency") or {}
        limits_first = sufficiency.get("summary") if sufficiency.get("level") in {"LIMITED", "INSUFFICIENT"} else ""
        lead = " ".join(part for part in (limits_first, text) if part) if text else ""  # limits: never the model's call
        note = MODEL_DOWN_NOTE if self._model_failed and not text else ""
        return "\n\n".join(part for part in (lead, rendered, note) if part)
