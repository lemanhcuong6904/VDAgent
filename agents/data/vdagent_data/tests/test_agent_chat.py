"""The explanation chat at the plugin boundary: who reaches it, and that the pipeline does not change.

A free-text message written by the user goes to the chat. Everything else keeps its path: a contract message (StepSpec@1 or
v1.0) runs the pipeline, free text from another agent still takes the legacy tool loop.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from vdagent_data import agent as agent_module
from vdagent_data.agent import NO_LLM_TEXT, DataAgent, build_agent
from vdagent_data.chat.loop import NO_PACKAGES_TEXT
from vdagent_data.tests.conftest import GrantedTools as McpTools
from vdagent_data.tests.conftest import McpPort
from vdagent_data.tests.test_agent_narration import StrictCtx
from vdagent_data.tests.test_agent_steps import factory
from vdagent_data.tests.test_chat_loop import ScriptedLLM, ask, say
from vdagent_data.tests.test_chat_tools import fetched
from vdagent_data.tests.test_steps import step
from vdagent_data.tests.test_v1_steps import ent


def ctx_from(sender: str, text: str) -> StrictCtx:
    ctx = StrictCtx(text)
    ctx.history = [{"role": "user", "content": f"[from: {sender}] {text}"}]
    return ctx


def chat_agent(tools: McpTools, llm: ScriptedLLM | None, **kwargs: Any) -> DataAgent:
    return DataAgent(llm=llm, mcp_session_factory=factory(tools), system_prompt="x", compact_prompt="y", chat_prompt="CHAT",
                     narrate_llm=False, **kwargs)


async def test_a_user_question_is_answered_from_the_fetched_package(mcp_tools: McpTools, alice: McpPort) -> None:
    await fetched(alice, "fetch_units", {"entities": [ent("A12-08", "UNIT")]})
    llm = ScriptedLLM(ask("get_resolution"), say("Mình lấy căn A12-08 vì bạn nhắc đúng mã đó."))
    ctx = ctx_from("user", "Tại sao lấy căn này?")
    await chat_agent(mcp_tools, llm).invoke(ctx)
    assert ctx.steps[-1] == ("Mình lấy căn A12-08 vì bạn nhắc đúng mã đó.", [])
    [(_, [call])] = [s for s in ctx.steps[:-1]]
    assert call.name == "get_resolution"
    assert llm.calls[0]["messages"][0] == {"role": "system", "content": "CHAT"}
    assert {t["function"]["name"] for t in llm.calls[0]["tools"]} >= {"get_overview", "get_unit", "get_missing", "define_term"}


async def test_before_any_data_the_user_is_told_so_without_calling_the_llm(mcp_tools: McpTools) -> None:
    llm = ScriptedLLM(say("không dùng"))
    ctx = ctx_from("user", "Căn A12-08 giá bao nhiêu?")
    await chat_agent(mcp_tools, llm).invoke(ctx)
    assert ctx.steps == [(NO_PACKAGES_TEXT, [])] and llm.calls == []


async def test_without_an_llm_the_chat_says_it_needs_one(mcp_tools: McpTools) -> None:
    ctx = ctx_from("user", "Căn A12-08 giá bao nhiêu?")
    await chat_agent(mcp_tools, None).invoke(ctx)
    assert ctx.steps == [(NO_LLM_TEXT, [])]


async def test_a_pipeline_step_never_reaches_the_chat(mcp_tools: McpTools) -> None:
    llm = ScriptedLLM(say("không dùng"))
    ctx = ctx_from("orchestrator", step().model_dump_json())
    await chat_agent(mcp_tools, llm).invoke(ctx)
    assert llm.calls == []
    assert json.loads(ctx.steps[-1][0].split("```json")[1].split("```")[0])["state"] == "completed"


async def test_free_text_from_another_agent_keeps_the_legacy_loop(mcp_tools: McpTools, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def legacy(self: Any, ctx: Any) -> None:
        seen.append(ctx.history[-1]["content"])

    monkeypatch.setattr(agent_module.LiteLLMAgent, "invoke", legacy)
    llm = ScriptedLLM(say("không dùng"))
    await chat_agent(mcp_tools, llm).invoke(ctx_from("orchestrator", "revenue by region?"))
    assert seen == ["[from: orchestrator] revenue by region?"] and llm.calls == []


def test_the_plugin_builds_with_a_chat_prompt() -> None:
    built = build_agent({"DATA_LLM": "off"})
    assert isinstance(built, DataAgent) and built.chat_prompt.strip()
