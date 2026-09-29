"""Whole Orchestrator turns with fake worker agents and a scripted LLM (source §13 H/V scenarios through the plugin)."""

from __future__ import annotations

import json
from typing import Any

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmRouter
from vdagent_agentkit.testing import InMemoryMemory, run_turn
from vdagent_orchestrator.agent import OrchestratorAgent
from vdagent_orchestrator.run_state import load_state
from vdagent_orchestrator.tests.helpers import (
    LANDMARK_INTENT,
    LANDMARK_PLAN,
    SCOPE,
    USER,
    Workers,
    ask,
    ctx,
    done,
    intent,
    mcp,
    plan,
    step,
)


def orchestrator(*script: str) -> tuple[OrchestratorAgent, FakeLLM]:
    llm = FakeLLM(list(script))
    return OrchestratorAgent(router=LlmRouter([llm]), mcp_session_factory=mcp().factory), llm


async def test_integration_landmark_with_fake_agents() -> None:
    memory, workers = InMemoryMemory(), Workers()
    agent, llm = orchestrator(LANDMARK_INTENT, LANDMARK_PLAN)
    turn = await run_turn(agent, ctx("Tại sao phân khu Landmark bán chậm?", workers, memory))
    assert workers.order() == ["B1", "B2", "B3", "B4", "B5"] and len(llm.calls) == 2
    b3 = next(s for a, s in workers.specs if s.step_id == "B3")
    assert [r.artifact_id for r in b3.input_refs] == ["art-B1", "art-B2"] and b3.snapshot_id == "snap-1"
    assert all(s.user_context == USER for _, s in workers.specs)  # from get_user_context, never from the LLM
    assert turn.final.startswith("**Kết quả:** Hoàn tất") and "B5 xong" in turn.final
    state = await load_state(memory)
    assert state.run is not None and state.run.finished and state.awaiting is None


async def test_integration_clarify_then_answer() -> None:
    memory, workers = InMemoryMemory(), Workers()
    agent, llm = orchestrator(intent(["EXPLAIN"], mentions=[], phenomena=["bán chậm"]), LANDMARK_INTENT, LANDMARK_PLAN)
    first = await run_turn(agent, ctx("Vì sao bán chậm?", workers, memory))
    assert "Bạn muốn xem dự án, phân khu hay căn nào?" in first.final and workers.specs == []
    second = await run_turn(agent, ctx("Landmark", workers, memory))
    assert "Landmark" in llm.calls[1]["messages"][1]["content"] and "Vì sao bán chậm?" in llm.calls[1]["messages"][1]["content"]
    assert "**Kết quả:** Hoàn tất" in second.final and len(workers.specs) == 5


async def test_integration_agent_question_two_turns() -> None:
    memory = InMemoryMemory()
    answered = Workers({"fetch_units": lambda s: done(s) if s.answered_choices else ask(s)})
    agent, _ = orchestrator(intent(["LOOKUP"], metrics=["unit_count"]),
                            plan(step("B1", "data", "fetch_units", scope=SCOPE)))
    first = await run_turn(agent, ctx("Landmark có những căn nào?", answered, memory))
    assert "Bạn muốn xem phân khu nào?" in first.final and "Không phải các lựa chọn này" in first.final
    second = await run_turn(agent, ctx("2", answered, memory))
    assert [(a.input_id, a.choice) for a in answered.specs[-1][1].answered_choices] == [("B1:0", "ZN-B")]
    assert "**Kết quả:** Hoàn tất" in second.final


async def test_integration_reject_and_no_llm() -> None:
    memory, workers = InMemoryMemory(), Workers()
    agent, _ = orchestrator(intent([], scope_check="OFF_TOPIC", mentions=[]))
    rejected = await run_turn(agent, ctx("Soạn email cho khách", workers, memory))
    assert "ngoài lĩnh vực" in rejected.final and workers.specs == []
    no_llm = OrchestratorAgent(router=None, mcp_session_factory=mcp().factory)
    lookup = await run_turn(no_llm, ctx("Tỷ lệ hấp thụ của Aqua 1 bao nhiêu?", workers, InMemoryMemory()))
    assert [s.operation for _, s in workers.specs] == ["aggregate_metrics"] and "chế độ giới hạn" in lookup.final
    failed = await run_turn(no_llm, ctx("Vì sao Aqua 1 bán chậm?", workers, InMemoryMemory()))
    assert "tạm thời không" in failed.final and len(workers.specs) == 1


async def test_integration_writes_run_state_and_summary_artifacts() -> None:
    puts: list[dict[str, Any]] = []
    llm = FakeLLM([LANDMARK_INTENT, LANDMARK_PLAN])
    agent = OrchestratorAgent(router=LlmRouter([llm]), mcp_session_factory=mcp(puts).factory)
    await run_turn(agent, ctx("Tại sao phân khu Landmark bán chậm?", Workers(), InMemoryMemory()))
    assert [p["artifact_type"] for p in puts] == ["run_state", "run_summary"]
    state, summary = puts
    assert state["run_id"] == summary["run_id"] == "t_1"  # anchors the run to the task that started it (DEC-045)
    assert [s["step_id"] for s in state["payload"]["steps"]] == ["B1", "B2", "B3", "B4", "B5"]
    assert "user_context" not in json.dumps(state) and summary["payload"]["status"] == "completed"
    assert [r["artifact_id"] for r in summary["input_artifact_refs"]] == ["art-B1", "art-B2", "art-B3", "art-B4", "art-B5"]
    assert summary["snapshot_refs"] == ["snap-1"] and summary["status"] == "VALID"
