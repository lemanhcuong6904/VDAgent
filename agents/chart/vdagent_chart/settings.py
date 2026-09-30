"""Local-only plugin settings; this module never mutates process environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ChartError

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    llm_model: str
    llm_timeout_s: float


def read_env(env_file: Path = ENV_FILE) -> dict[str, str]:
    values = dict(os.environ)
    if not env_file.is_file():
        return values
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key and not key.lstrip().startswith("#"):
            values[key.strip()] = value.strip()
    return values


def load_settings(env: Mapping[str, str]) -> Settings:
    api_key = env.get("OPENAI_API_KEY", "").strip()
    base_url = env.get("OPENAI_BASE_URL", "").strip()
    if not api_key:
        raise ChartError("CFG-001", "missing required environment variable OPENAI_API_KEY", "configuration")
    if not base_url:
        raise ChartError("CFG-002", "missing required environment variable OPENAI_BASE_URL", "configuration")
    raw_timeout = env.get("LLM_TIMEOUT_S", "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_S
    except ValueError as exc:
        raise ChartError("CFG-003", "LLM_TIMEOUT_S must be a number", "configuration") from exc
    if timeout <= 0:
        raise ChartError("CFG-004", "LLM_TIMEOUT_S must be positive", "configuration")
    return Settings(api_key, base_url, env.get("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL, timeout)
