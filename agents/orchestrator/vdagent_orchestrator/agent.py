"""The Orchestrator plugin (Orchestrator v4 on the SDK; D3 centralized waves; DEC-025 turn-based questions).

One turn: load the conversation state from `ctx.memory`, route the message (new question, clarification answer, answer
to an agent's or the decision card, or "go on"), then understand → clarify rules → plan → dispatch in waves (one
assistant step with one `send_to_agent` call per step of the wave) → replan → cards or the closing summary. State is
saved back to memory (R1); every LLM call of a question counts against `MAX_LLM_CALLS` (source §2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping, Sequence

from vdagent_sdk import SEND_TO_AGENT, InvocationContext, Message, PluginConfigError, ToolCall

from vdagent_agentkit.llm import CallBudget, LlmRouter
from vdagent_agentkit.mcp_client import McpSession, McpSessionFactory, open_mcp_session
from vdagent_agentkit.settings import load_llm_settings
from vdagent_contracts.scope import UserContext
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.checker import RunState
from vdagent_orchestrator.close import RunSummary, failure_text, plan_failed_summary, render_markdown
from vdagent_orchestrator.decision import answer_decision, open_decision
from vdagent_orchestrator.dispatcher import TIMEOUT_REPLY, Outbound, drive, ready
from vdagent_orchestrator.inputs import answer, open_question
from vdagent_orchestrator.intent import decide
from vdagent_orchestrator.lineage import put, run_state_draft, run_summary_draft
from vdagent_orchestrator.llm1 import understand
from vdagent_orchestrator.planner import make_plan
from vdagent_orchestrator.records import RunRecord, new_run
from vdagent_orchestrator.replan import replan, tier2_available
from vdagent_orchestrator.run_state import Awaiting, ConversationState, load_state, route_message, save_state
from vdagent_orchestrator.wording import part

NAME = "orchestrator"
DESCRIPTION = ("Orchestrator: hiểu câu hỏi của Sales Ops, lập kế hoạch từ catalog, điều phối Data/Compare/Insight/Chart/"
               "Report theo đợt và tổng kết kết quả.")
MAX_LLM_CALLS = 9
CONTINUE_TEXT = "Còn phần đang xử lý. Gửi \"tiếp tục\" (hoặc tin nhắn bất kỳ) để chạy tiếp."
NO_MATCH_TEXT = "Chưa nhận ra lựa chọn của bạn. Hãy trả lời bằng số thứ tự hoặc tên lựa chọn:"
_FROM = re.compile(r"^\[from: [^\]]+\]\s*")
log = logging.getLogger(__name__)


class CtxSender:
    """One wave = one assistant step with a `send_to_agent` call per step; calls run concurrently (R2–R4)."""

    def __init__(self, ctx: InvocationContext, waves: int) -> None:
        self._ctx = ctx
        self.remaining = waves
        self._sent = 0

    async def send(self, wave: Sequence[Outbound]) -> list[str]:
        self.remaining -= 1
        self._sent += 1
        calls = [ToolCall(id=f"w{self._sent}-{o.step_id}", name=SEND_TO_AGENT,
                          arguments_json=json.dumps({"agent": o.agent, "message": o.message}, ensure_ascii=False))
                 for o in wave]
        await self._ctx.emit_assistant("Đang chạy: " + ", ".join(dict.fromkeys(part(o.agent) for o in wave)) + ".", calls)

        async def one(call: ToolCall, item: Outbound) -> str:
            try:
                async with asyncio.timeout(item.timeout_s):
                    reply = await self._ctx.call_agent(call.id, item.agent, item.message)
            except TimeoutError:
                reply = TIMEOUT_REPLY
            await self._ctx.emit_tool_result(call.id, reply)
            return reply

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(one(c, o)) for c, o in zip(calls, wave, strict=True)]
        return [t.result() for t in tasks]


class _Turn:
    """State of one `invoke` (R8: kept off the agent object)."""

    def __init__(self, agent: OrchestratorAgent, ctx: InvocationContext, session: McpSession, state: ConversationState) -> None:
        self.ctx, self.session, self.state, self.registry = ctx, session, state, agent.registry
        self.budget = CallBudget(limit=MAX_LLM_CALLS, used=state.llm_calls)
        self.router = agent.router.with_budget(self.budget) if agent.router else None
        self.sender = CtxSender(ctx, max(ctx.max_steps - 1, 0))  # the last step is the answer (R7)

    async def run(self, text: str) -> str:
        route = route_message(self.state, text)
        if route == "NEW_QUESTION":
            previous = self.state.run
            self.state = ConversationState()
            self.budget.used = 0
            return await self._question(text, [], 0, previous if previous and previous.finished else None)
        if route == "CLARIFY_ANSWER":
            assert self.state.awaiting is not None
            question, answers, rounds = self.state.awaiting.resume_clarify(text)
            self.state.awaiting = None
            return await self._question(question, answers, rounds, None)
        run = self.state.run
        assert run is not None
        if route == "ANSWER" and answer(run, text) == "NO_MATCH":
            card = open_question(run)
            return f"{NO_MATCH_TEXT}\n{card.render()}" if card else await self._advance(run)
        if route == "DECISION_ANSWER" and answer_decision(run, text) == "NO_MATCH":
            decision = open_decision(run)
            return f"{NO_MATCH_TEXT}\n{decision.render()}" if decision else await self._advance(run)
        self.state.awaiting = None
        return await self._advance(run)

    async def _question(self, question: str, answers: list[str], rounds: int, parent: RunRecord | None) -> str:
        understood = await understand(question, router=self.router, registry=self.registry, clarify_answers=answers,
                                      parent_frame=parent.frame if parent else None)
        if understood.draft is None:
            return failure_text("LLM_UNAVAILABLE")
        metrics = [m.name for m in self.registry.catalogs["data"].vocabulary.metrics][:3]
        decision = decide(understood.draft, question=question, served=self.registry.served_kinds(), clarify_rounds=rounds,
                          metric_suggestions=metrics)
        if decision.decision == "REJECT":
            return decision.reason or ""
        if decision.decision == "ASK":
            self.state.awaiting = Awaiting(kind="CLARIFY", question=question, questions=decision.questions,
                                           answers=answers, rounds=rounds + 1)
            return "\n".join(decision.questions)
        assert decision.frame is not None
        frame = decision.frame.model_copy(update={"source": understood.source,
                                                  "parent_run_id": parent.plan.plan_id if parent else None})
        outcome = await self.session.call_tool("get_user_context", {})
        if outcome.is_error:
            return failure_text("NO_USER_CONTEXT")
        user_context = UserContext.model_validate_json(outcome.text)
        planned = await make_plan(frame, router=self.router, registry=self.registry, run_id=self.ctx.task_id,
                                  plan_id=f"plan-{self.ctx.invocation_id}", state=RunState(), next_step_no=1,
                                  snapshot_pinned=False)
        if planned.plan is None:
            return render_markdown(plan_failed_summary(frame, planned.reason or "PLAN_REJECTED"))
        run = new_run(planned.plan, planned.frame, user_context=user_context)
        self.state.run = run
        await put(self.session, run_state_draft(run), run.run_id)  # anchors the run to this task (DEC-045)
        return await self._advance(run)

    async def _advance(self, run: RunRecord) -> str:
        while True:
            run = await drive(run, sender=self.sender, registry=self.registry,
                              tier2_available=tier2_available(run, self.router), max_waves=self.sender.remaining)
            run = await replan(run, router=self.router, registry=self.registry)
            card = open_question(run)
            if card is not None:
                self.state.awaiting = Awaiting(kind="AGENT_QUESTION", input_id=card.input_id)
                return card.render()
            if not ready(run) or self.sender.remaining <= 0:
                break
        decision = open_decision(run)
        if decision is not None:
            self.state.awaiting = Awaiting(kind="DECISION", input_id=decision.input_id)
            return decision.render()
        if run.finished and run.summary is not None:
            if run.summary_artifact_id is None:
                run.summary_artifact_id = await put(self.session, run_summary_draft(run), run.run_id)
            return render_markdown(RunSummary.model_validate(run.summary))
        return CONTINUE_TEXT

    def finish(self) -> ConversationState:
        self.state.llm_calls = self.budget.used
        if self.state.run is not None:
            self.state.run.llm_calls = self.budget.used
        return self.state


class OrchestratorAgent:
    def __init__(self, *, router: LlmRouter | None, mcp_session_factory: McpSessionFactory = open_mcp_session,
                 registry: CatalogRegistry | None = None) -> None:
        self.router = router
        self.registry = registry or CatalogRegistry.load()
        self._mcp = mcp_session_factory

    async def invoke(self, ctx: InvocationContext) -> None:
        text = _FROM.sub("", ctx.history[-1]["content"] if ctx.history else "", count=1).strip()
        state = await load_state(ctx.memory)
        async with self._mcp(ctx.mcp.url, ctx.mcp.token) as session:
            turn = _Turn(self, ctx, session, state)
            reply = await turn.run(text)
        await save_state(ctx.memory, turn.finish())
        await ctx.emit_assistant(reply)

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        """Run state lives in memory (R1); the conversation needs no extra summary."""
        return previous_summary


def build_agent(env: Mapping[str, str]) -> OrchestratorAgent:
    """LLM settings are optional: without them only SIMPLE_ROUTER lookups with a fallback plan are served (INT-4, §6.5)."""
    try:
        router: LlmRouter | None = load_llm_settings(env).router()
    except PluginConfigError as exc:
        log.warning("orchestrator without LLM (%s): simple lookups only", exc)
        router = None
    return OrchestratorAgent(router=router)


__all__ = ["DESCRIPTION", "MAX_LLM_CALLS", "NAME", "CtxSender", "OrchestratorAgent", "build_agent"]
