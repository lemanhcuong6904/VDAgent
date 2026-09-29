"""The Orchestrator plugin: setup, budgets (source §2: 9 LLM calls, 10 steps + 2 retries, ctx.max_steps) and the SDK
contract checks R2–R11 through `vdagent_agentkit.testing`."""

from __future__ import annotations

import asyncio
import json
import os

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmRouter
from vdagent_agentkit.testing import ContractContext, InMemoryMemory, assert_cancel_propagates, run_turn
from vdagent_orchestrator import setup
from vdagent_orchestrator.agent import DESCRIPTION, NAME, MAX_LLM_CALLS, OrchestratorAgent, build_agent
from vdagent_orchestrator.dispatcher import tier3_eligible
from vdagent_orchestrator.run_state import Awaiting, ConversationState, load_state, save_state
from vdagent_orchestrator.tests.helpers import (
    LANDMARK_INTENT,
    LANDMARK_PLAN,
    SCOPE,
    Workers,
    ctx,
    intent,
    mcp,
    plan,
    step,
)
from vdagent_orchestrator.tests.test_replan import base


def agent(*script: str, llm: FakeLLM | None = None) -> OrchestratorAgent:
    fake = llm or FakeLLM(list(script))
    return OrchestratorAgent(router=LlmRouter([fake]), mcp_session_factory=mcp().factory)


class Api:
    def __init__(self) -> None:
        self.registered: list[tuple[str, str, object]] = []

    def register_agent(self, *, name: str, description: str, agent: object) -> None:
        self.registered.append((name, description, agent))


def test_setup_registers_orchestrator_without_llm_settings() -> None:
    api = Api()
    before = dict(os.environ)
    setup(api, {})  # type: ignore[arg-type]
    assert [(n, d) for n, d, _ in api.registered] == [(NAME, DESCRIPTION)] and dict(os.environ) == before
    assert isinstance(build_agent({}), OrchestratorAgent)  # no LLM settings: SIMPLE_ROUTER + fallback plans only


async def test_budget_9_llm_calls_per_run() -> None:
    memory = InMemoryMemory()
    clarify = Awaiting(kind="CLARIFY", question="DOM trung bình bao nhiêu?", questions=["Phạm vi?"], rounds=1)
    await save_state(memory, ConversationState(awaiting=clarify, llm_calls=MAX_LLM_CALLS - 1))
    llm = FakeLLM([intent(["LOOKUP"], metrics=["avg_dom_unsold"]), LANDMARK_PLAN])
    workers = Workers()
    turn = await run_turn(agent(llm=llm), ctx("Landmark", workers, memory))
    assert len(llm.calls) == 1  # LLM 1 used the last call; LLM 2 is never called
    assert "chế độ giới hạn" in turn.final and workers.order() == ["B1"]  # fallback plan (§6.5)
    state = await load_state(memory)
    assert state.llm_calls == MAX_LLM_CALLS and state.run is not None and state.run.plan.source == "FALLBACK"


async def test_budget_10_steps_plus_2_retry() -> None:
    eleven = plan(*[step(f"B{i}", "data", "aggregate_metrics", scope=SCOPE, metrics=["unit_count"]) for i in range(1, 12)])
    memory = InMemoryMemory()
    workers = Workers()
    turn = await run_turn(agent(intent(["LOOKUP"], metrics=["unit_count"]), eleven, eleven),
                          ctx("Landmark có bao nhiêu căn?", workers, memory))
    assert workers.specs == [] and "không lập được kế hoạch hợp lệ" in turn.final
    ten = base(*[step(f"B{i}", "data", "aggregate_metrics", scope=SCOPE, metrics=["unit_count"]) for i in range(4, 11)])
    assert len(ten.steps) == 10 and tier3_eligible(ten)  # a retry may go past 10 steps …
    ten.retry_reserve_used = 2
    assert not tier3_eligible(ten)  # … at most twice


async def test_respects_ctx_max_steps() -> None:
    memory = InMemoryMemory()
    workers = Workers()
    orchestrator = agent(LANDMARK_INTENT, LANDMARK_PLAN)
    first = await run_turn(orchestrator, ctx("Tại sao phân khu Landmark bán chậm?", workers, memory, max_steps=3))
    assert first.assistant_steps <= 3 and workers.order() == ["B1", "B2"]
    assert "tiếp tục" in first.final
    second = await run_turn(orchestrator, ctx("tiếp tục", workers, memory, max_steps=3))
    third = await run_turn(orchestrator, ctx("ok", workers, memory, max_steps=3))
    assert second.assistant_steps <= 3 and third.assistant_steps <= 3
    assert workers.order() == ["B1", "B2", "B3", "B4", "B5"] and "**Kết quả:** Hoàn tất" in third.final


async def test_sdk_contract_suite() -> None:
    memory = InMemoryMemory()
    workers = Workers()
    turn = await run_turn(agent(LANDMARK_INTENT, LANDMARK_PLAN), ctx("Tại sao phân khu Landmark bán chậm?", workers, memory))
    calls = [e for e in turn.events if e[0] == "assistant" and e[2]]
    assert all(name == "send_to_agent" for _, _, tcs in calls for _, name, _ in tcs)
    assert all(json.loads(args)["agent"] in {"data", "insight", "chart", "report"} for _, _, tcs in calls for _, _, args in tcs)

    async def hang(message: str) -> str:
        await asyncio.sleep(3600)
        return ""

    hanging = ContractContext(inbound="[from: user] Tại sao phân khu Landmark bán chậm?", memory_store=InMemoryMemory(),
                              agents={**workers.agents(), "data": hang})
    await assert_cancel_propagates(agent(LANDMARK_INTENT, LANDMARK_PLAN), hanging)
    assert await agent().compact("tóm tắt cũ", []) == "tóm tắt cũ"
