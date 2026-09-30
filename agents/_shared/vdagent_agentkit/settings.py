"""LLM settings from a plugin's `.env` over the process environment, without writing `os.environ` (R11, D9).

Required: OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL. Optional fallback provider: FALLBACK_LLM_MODEL (+ FALLBACK_
OPENAI_API_KEY / FALLBACK_OPENAI_BASE_URL, defaulting to the primary credentials). LLM_TIMEOUT_S default 120.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from vdagent_sdk import PluginConfigError

from vdagent_agentkit.llm import LiteLLMClient, LlmRouter

REQUIRED_VARS: tuple[str, ...] = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL")
DEFAULT_LLM_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class ProviderSettings:
    model: str
    api_base: str
    api_key: str
    reasoning_effort: str | None = None  # LLM_REASONING_EFFORT, e.g. "none" for reasoning models at temperature 0


@dataclass(frozen=True)
class LlmSettings:
    primary: ProviderSettings
    fallback: ProviderSettings | None
    timeout_s: float

    def router(self) -> LlmRouter:
        providers = [self.primary] + ([self.fallback] if self.fallback else [])
        return LlmRouter(
            [LiteLLMClient(model=p.model, api_base=p.api_base, api_key=p.api_key, timeout_s=self.timeout_s,
                           reasoning_effort=p.reasoning_effort) for p in providers]
        )


def read_env(env_file: Path) -> dict[str, str]:
    """The process environment overlaid with `env_file` (the file wins; a missing file is fine)."""
    from_file = dotenv_values(env_file) if env_file.is_file() else {}
    return {**os.environ, **{k: v for k, v in from_file.items() if v is not None}}


def load_llm_settings(env: Mapping[str, str]) -> LlmSettings:
    for var in REQUIRED_VARS:
        if not env.get(var, "").strip():
            raise PluginConfigError(f"missing required environment variable {var}")
    raw_timeout = env.get("LLM_TIMEOUT_S", "").strip()
    try:
        timeout_s = float(raw_timeout) if raw_timeout else DEFAULT_LLM_TIMEOUT_S
    except ValueError:
        raise PluginConfigError(f"LLM_TIMEOUT_S must be a number; got {raw_timeout!r}") from None
    if timeout_s <= 0:
        raise PluginConfigError(f"LLM_TIMEOUT_S must be positive; got {timeout_s:g}")
    primary = ProviderSettings(
        model=env["LLM_MODEL"].strip(), api_base=env["OPENAI_BASE_URL"].strip(), api_key=env["OPENAI_API_KEY"].strip(),
        reasoning_effort=env.get("LLM_REASONING_EFFORT", "").strip() or None,
    )
    fallback_model = env.get("FALLBACK_LLM_MODEL", "").strip()
    fallback = (
        ProviderSettings(
            model=fallback_model,
            api_base=env.get("FALLBACK_OPENAI_BASE_URL", "").strip() or primary.api_base,
            api_key=env.get("FALLBACK_OPENAI_API_KEY", "").strip() or primary.api_key,
            reasoning_effort=env.get("FALLBACK_LLM_REASONING_EFFORT", "").strip() or None,
        )
        if fallback_model
        else None
    )
    return LlmSettings(primary=primary, fallback=fallback, timeout_s=timeout_s)
