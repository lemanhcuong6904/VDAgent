"""LLM settings: this plugin folder's `.env` over the Backend's process environment.

Every plugin shares the Backend's process, so the `.env` is read with `dotenv_values()` into a
mapping and `os.environ` is never modified (it is shared with every other plugin).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from vdagent_sdk import PluginConfigError

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"  # agents/<name>/.env
REQUIRED_VARS: tuple[str, ...] = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL")
DEFAULT_LLM_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    llm_model: str
    llm_timeout_s: float


def read_env(env_file: Path = ENV_FILE) -> dict[str, str]:
    """The process environment overlaid with `env_file` (the file wins; a missing file is fine)."""
    from_file = dotenv_values(env_file) if env_file.is_file() else {}
    return {**os.environ, **{k: v for k, v in from_file.items() if v is not None}}


def load_settings(env: Mapping[str, str]) -> Settings:
    """Read and validate the LLM settings; `PluginConfigError` names the offending variable."""
    for var in REQUIRED_VARS:
        if not env.get(var, "").strip():
            raise PluginConfigError(f"missing required environment variable {var}")
    raw_timeout = env.get("LLM_TIMEOUT_S", "").strip()
    try:
        llm_timeout_s = float(raw_timeout) if raw_timeout else DEFAULT_LLM_TIMEOUT_S
    except ValueError:
        raise PluginConfigError(f"LLM_TIMEOUT_S must be a number; got {raw_timeout!r}") from None
    if llm_timeout_s <= 0:
        raise PluginConfigError(f"LLM_TIMEOUT_S must be positive; got {llm_timeout_s:g}")
    return Settings(
        openai_api_key=env["OPENAI_API_KEY"].strip(),
        openai_base_url=env["OPENAI_BASE_URL"].strip(),
        llm_model=env["LLM_MODEL"].strip(),
        llm_timeout_s=llm_timeout_s,
    )
