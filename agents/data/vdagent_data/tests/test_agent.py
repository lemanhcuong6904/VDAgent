"""The Data plugin: registration, one report per turn, free text, and the SDK rules R2–R11 (shared checks)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import LlmRouter
from vdagent_agentkit.testing import ContractContext, assert_cancel_propagates, run_turn
from vdagent_contracts.reports import AgentReport, parse_agent_report
from vdagent_data import setup
from vdagent_data.agent import NAME, DataAgent, build_agent
from vdagent_data.tests.conftest import step
from vdagent_data.tests.fakes import DwMcp
from vdagent_sdk import Agent


@dataclass
class FakeAPI:
    agents: dict[str, tuple[str, Agent]] = field(default_factory=dict)
    plugin: str = "test"
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("test"))

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        self.agents[name] = (description, agent)

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        raise AssertionError("no shutdown hook expected")


def report_of(ctx: ContractContext) -> AgentReport:
    parsed = parse_agent_report(ctx.final)
    assert isinstance(parsed, AgentReport), parsed
    return parsed


def test_setup_registers_data_agent_without_llm_settings() -> None:
    api = FakeAPI()
    setup(api, {})
    assert NAME in api.agents and "StepSpec@1" in api.agents[NAME][0]
    assert isinstance(build_agent({}), DataAgent)  # no LLM env: T1/T2 still work


async def test_stepspec_turn_emits_one_report(dw_path: str) -> None:
    mcp = DwMcp(dw_path)
    agent = DataAgent(router=None, mcp_session_factory=mcp.factory)
    message = "[from: orchestrator] " + step().model_dump_json()
    ctx = await run_turn(agent, ContractContext(inbound=message))
    assert ctx.assistant_steps == 1
    report = report_of(ctx)
    assert report.state == "completed" and report.artifact_refs and report.step_id == "B1"


async def test_free_text_converted_to_stepspec_or_guidance(dw_path: str) -> None:
    mcp = DwMcp(dw_path)
    request = {"answerable": True, "operation": "aggregate_metrics", "mentions": [{"text": "Tòa Aqua 1", "kind_hint": "ZONE"}],
               "metrics": ["slow_moving_count"], "group_by": [], "filters": []}
    llm = FakeLLM([json.dumps(request), json.dumps({"text": "Tòa Aqua 1 có 40 căn bán chậm."})])
    agent = DataAgent(router=LlmRouter([llm]), mcp_session_factory=mcp.factory)
    ctx = await run_turn(agent, ContractContext(inbound="[from: user] Tòa Aqua 1 có bao nhiêu căn bán chậm?"))
    report = report_of(ctx)
    assert report.state == "completed" and "40" in report.summary
    assert "<data>" in llm.calls[0]["messages"][-1]["content"]
    refuse = FakeLLM([json.dumps({"answerable": False, "guidance": "Tôi chỉ trả lời câu hỏi số liệu tồn kho, giá, tốc độ bán."})])
    ctx = await run_turn(DataAgent(router=LlmRouter([refuse]), mcp_session_factory=mcp.factory),
                         ContractContext(inbound="Soạn email cho khách"))
    assert report_of(ctx).state == "rejected"
    no_llm = await run_turn(DataAgent(router=None, mcp_session_factory=mcp.factory), ContractContext(inbound="DOM?"))
    assert report_of(no_llm).error is not None


async def test_other_contract_or_bad_json_rejected(dw_path: str) -> None:
    agent = DataAgent(router=None, mcp_session_factory=DwMcp(dw_path).factory)
    for inbound in ('{"contract": "CompareRequest@1"}', '{"no": "contract"}', '{"contract": "StepSpec@1", "run_id": 1}'):
        report = report_of(await run_turn(agent, ContractContext(inbound=inbound)))
        assert report.state == "rejected" and report.error is not None


async def test_cancel_propagates(dw_path: str) -> None:
    agent = DataAgent(router=None, mcp_session_factory=DwMcp(dw_path, delay_s=0.2).factory)
    await assert_cancel_propagates(agent, ContractContext(inbound=step().model_dump_json()))


async def test_compact_keeps_summary() -> None:
    assert await DataAgent(router=None).compact("tóm tắt", []) == "tóm tắt"
