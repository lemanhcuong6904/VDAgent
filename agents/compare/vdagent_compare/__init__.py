"""Compare plugin entry point. The Backend imports this module (listed under `plugins:` in
`backend/config.yaml`) and calls `setup(api, opts)` once at startup.

The deterministic engine always answers. When `agents/compare/.env` holds `OPENAI_API_KEY`, a model
(default `gpt-6-luna`, falling back to `gpt-4o-mini`) plans comparisons and words the answers;
without it the plugin still loads and answers with rules and templates.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from vdagent_sdk import PluginAPI

log = logging.getLogger(__name__)


def read_env() -> dict[str, str]:
    from .settings import read_env as load

    return load()


def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None:
    """`opts` is accepted for compatibility (`vhop_demo`); configuration lives in the plugin's `.env`."""
    from .agent import DESCRIPTION, NAME, CompareAgent
    from .settings import load_llm_settings

    settings = load_llm_settings(read_env())
    llm = None
    if settings is not None:
        from .llm import LiteLLMJsonClient

        for noisy in ("httpx", "LiteLLM"):  # per-request INFO lines drown out agent logs
            logging.getLogger(noisy).setLevel(logging.WARNING)
        llm = LiteLLMJsonClient(models=settings.models, api_base=settings.openai_base_url,
                                api_key=settings.openai_api_key, timeout_s=settings.llm_timeout_s)
    log.info("compare: model %s", ", ".join(settings.models) if settings else "off (rules and templates)")
    api.register_agent(name=NAME, description=DESCRIPTION, agent=CompareAgent(llm=llm))
