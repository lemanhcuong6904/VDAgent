from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from vdagent_agentkit.fake_llm import FakeLLM
from vdagent_agentkit.llm import CallBudget, LiteLLMClient, LlmError, LlmErrorCode, LlmRouter, LlmUsage
from vdagent_agentkit.settings import load_llm_settings, read_env
from vdagent_sdk import PluginConfigError


class Pick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    group_by: list[str]


MESSAGES = [{"role": "user", "content": "DOM theo nhóm tầng?"}]


async def test_structured_output_validated_by_pydantic() -> None:
    llm = FakeLLM(['{"metric": "avg_dom_unsold", "group_by": ["floor_band"]}'])
    result = await LlmRouter([llm]).structured(Pick, MESSAGES)
    assert result.value == Pick(metric="avg_dom_unsold", group_by=["floor_band"])
    assert result.calls == 1
    schema = llm.calls[0]["schema"]
    assert schema["properties"]["metric"]["type"] == "string"  # JSON Schema generated from the model


async def test_invalid_json_one_repair_then_error() -> None:
    llm = FakeLLM(['{"metric": 1}', '{"metric": "avg_dom_unsold", "group_by": []}'])
    result = await LlmRouter([llm]).structured(Pick, MESSAGES)
    assert result.value.metric == "avg_dom_unsold" and result.calls == 2
    assert "invalid" in llm.calls[1]["messages"][-1]["content"].lower()  # the repair call names the problem
    bad = FakeLLM(["not json", '{"metric": 2}'])
    with pytest.raises(LlmError) as exc:
        await LlmRouter([bad]).structured(Pick, MESSAGES)
    assert exc.value.code is LlmErrorCode.INVALID_OUTPUT
    assert exc.value.calls == 2


async def test_primary_fail_uses_fallback() -> None:
    primary = FakeLLM([LlmError(LlmErrorCode.TRANSIENT, "503")], model="gemini-x")
    fallback = FakeLLM(['{"metric": "absorption_rate", "group_by": []}'], model="gpt-y")
    result = await LlmRouter([primary, fallback]).structured(Pick, MESSAGES)
    assert result.value.metric == "absorption_rate"
    assert [u.model for u in result.usage] == ["gemini-x", "gpt-y"]  # failed attempts are counted too


async def test_error_mapped_llm_unavailable_vs_quota() -> None:
    down = [FakeLLM([LlmError(LlmErrorCode.TRANSIENT, "timeout")]), FakeLLM([LlmError(LlmErrorCode.TRANSIENT, "503")])]
    with pytest.raises(LlmError) as exc:
        await LlmRouter(down).structured(Pick, MESSAGES)
    assert exc.value.code is LlmErrorCode.UNAVAILABLE and exc.value.agent_code == "LLM_UNAVAILABLE"
    quota = [FakeLLM([LlmError(LlmErrorCode.QUOTA_EXHAUSTED, "quota")]), FakeLLM([LlmError(LlmErrorCode.QUOTA_EXHAUSTED, "q")])]
    with pytest.raises(LlmError) as exc:
        await LlmRouter(quota).structured(Pick, MESSAGES)
    assert exc.value.code is LlmErrorCode.QUOTA_EXHAUSTED and exc.value.agent_code == "LLM_QUOTA_EXHAUSTED"


async def test_fake_llm_scripted_sequence() -> None:
    llm = FakeLLM(['{"metric": "a", "group_by": []}', lambda msgs, schema: '{"metric": "b", "group_by": []}'])
    router = LlmRouter([llm])
    assert (await router.structured(Pick, MESSAGES)).value.metric == "a"
    assert (await router.structured(Pick, MESSAGES)).value.metric == "b"
    assert len(llm.calls) == 2


async def test_fake_llm_exhausted_raises() -> None:
    llm = FakeLLM([])
    with pytest.raises(AssertionError, match="script exhausted"):
        await LlmRouter([llm]).structured(Pick, MESSAGES)


def test_settings_never_writes_environ(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=k\nOPENAI_BASE_URL=http://x\nLLM_MODEL=m\nFALLBACK_LLM_MODEL=m2\n")
    before = dict(os.environ)
    env = read_env(env_file)
    assert dict(os.environ) == before
    settings = load_llm_settings(env)
    assert settings.primary.model == "m" and settings.fallback is not None and settings.fallback.model == "m2"
    assert settings.fallback.api_key == "k"  # fallback inherits unset credentials
    with pytest.raises(PluginConfigError, match="LLM_MODEL"):
        load_llm_settings({"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "u"})


async def test_usage_tokens_recorded() -> None:
    llm = FakeLLM(['{"metric": "a", "group_by": []}'], usage=LlmUsage(model="m", prompt_tokens=100, output_tokens=20))
    result = await LlmRouter([llm]).structured(Pick, MESSAGES)
    assert result.usage == [LlmUsage(model="m", prompt_tokens=100, output_tokens=20)]


async def test_router_with_budget_counts_every_provider_call() -> None:
    primary = FakeLLM([LlmError(LlmErrorCode.TRANSIENT, "503"), "not json"], model="p")
    fallback = FakeLLM(['{"metric": "unit_count", "group_by": []}', '{"metric": "unit_count", "group_by": []}'], model="f")
    budget = CallBudget(limit=3)
    router = LlmRouter([primary, fallback]).with_budget(budget)
    result = await router.structured(Pick, MESSAGES)  # primary fails, fallback answers: 2 provider calls
    assert result.value.metric == "unit_count" and budget.used == 2
    with pytest.raises(LlmError) as exc:  # 1 call left: the primary's invalid JSON, then the cap
        await router.structured(Pick, MESSAGES)
    assert exc.value.agent_code == "LLM_UNAVAILABLE" and budget.used == 3 and budget.exhausted
    assert len(fallback.calls) == 1  # capped calls never reach a provider


async def test_litellm_client_sends_reasoning_effort_and_maps_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    seen: dict[str, Any] = {}

    class Choice:
        finish_reason = "stop"
        message = type("M", (), {"content": '{"metric": "unit_count", "group_by": []}'})()

    async def ok(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return type("R", (), {"choices": [Choice()], "usage": None})()

    monkeypatch.setattr(litellm, "acompletion", ok)
    client = LiteLLMClient(model="gpt-x", api_base="http://llm", api_key="k", timeout_s=5, reasoning_effort="none")
    result = await LlmRouter([client]).structured(Pick, MESSAGES)
    assert result.value.metric == "unit_count" and seen["reasoning_effort"] == "none" and seen["temperature"] == 0.0

    async def rejected(**kwargs: Any) -> Any:  # e.g. a reasoning model refusing temperature=0
        raise litellm.UnsupportedParamsError(message="temperature=0.0 not supported", model="gpt-x", llm_provider="openai")

    monkeypatch.setattr(litellm, "acompletion", rejected)
    with pytest.raises(LlmError) as exc:  # never an unhandled provider exception: callers degrade (INT-4)
        await LlmRouter([LiteLLMClient(model="gpt-x", api_base="http://llm", api_key="k", timeout_s=5)]).structured(Pick, MESSAGES)
    assert exc.value.agent_code == "LLM_UNAVAILABLE" and "temperature" in exc.value.message


def test_settings_read_reasoning_effort() -> None:
    env = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://llm", "LLM_MODEL": "m", "LLM_REASONING_EFFORT": "none",
           "FALLBACK_LLM_MODEL": "f", "FALLBACK_LLM_REASONING_EFFORT": "low"}
    settings = load_llm_settings(env)
    assert settings.primary.reasoning_effort == "none" and settings.fallback is not None
    assert settings.fallback.reasoning_effort == "low"
    assert load_llm_settings({**env, "LLM_REASONING_EFFORT": ""}).primary.reasoning_effort is None
