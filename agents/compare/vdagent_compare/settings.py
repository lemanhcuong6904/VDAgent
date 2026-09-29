"""Model settings: this plugin folder's `.env` over the Backend's process environment.

Every plugin shares the Backend's process, so the `.env` is read with `dotenv_values()` into a
mapping and `os.environ` is never modified (SDK rule R11). The model is optional: without
`OPENAI_API_KEY` (or with `COMPARE_LLM=off`) Compare answers with rules and templates only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from vdagent_sdk import PluginConfigError

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"  # agents/<name>/.env
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6-luna"  # spec §1.9: planning and wording
DEFAULT_FALLBACK_MODEL = "gpt-4o-mini"
DEFAULT_LLM_TIMEOUT_S = 20.0  # the step deadline is 30 s (spec §3.4); two calls must fit


@dataclass(frozen=True)
class LLMSettings:
    openai_api_key: str
    openai_base_url: str
    models: tuple[str, ...]
    llm_timeout_s: float


def read_env(env_file: Path = ENV_FILE) -> dict[str, str]:
    """The process environment overlaid with `env_file` (the file wins; a missing file is fine)."""
    from_file = dotenv_values(env_file) if env_file.is_file() else {}
    return {**os.environ, **{k: v for k, v in from_file.items() if v is not None}}


def load_llm_settings(env: Mapping[str, str]) -> LLMSettings | None:
    """`None` when no model should be used; `PluginConfigError` names a malformed variable."""
    key = env.get("OPENAI_API_KEY", "").strip()
    if not key or env.get("COMPARE_LLM", "").strip().lower() in {"off", "0", "false", "no"}:
        return None
    raw_timeout = env.get("LLM_TIMEOUT_S", "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_LLM_TIMEOUT_S
    except ValueError:
        raise PluginConfigError(f"LLM_TIMEOUT_S must be a number; got {raw_timeout!r}") from None
    if timeout <= 0:
        raise PluginConfigError(f"LLM_TIMEOUT_S must be positive; got {timeout:g}")
    primary = env.get("LLM_MODEL", "").strip() or DEFAULT_MODEL
    fallback = env.get("LLM_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL).strip()
    models = tuple(dict.fromkeys(m for m in (primary, fallback) if m))
    return LLMSettings(
        openai_api_key=key,
        openai_base_url=env.get("OPENAI_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        models=models,
        llm_timeout_s=timeout,
    )
