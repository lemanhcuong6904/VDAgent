"""vdagent Orchestrator plugin (Orchestrator v4). The Backend imports this module, listed under `plugins:` in
`backend/config.yaml`, and calls `setup(api, opts)` once at startup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vdagent_sdk import PluginAPI

from vdagent_agentkit.settings import read_env

from .agent import DESCRIPTION, NAME, build_agent

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"  # agents/orchestrator/.env


def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None:
    """Register the Orchestrator, configured by this plugin folder's `.env` (LLM settings optional)."""
    api.register_agent(name=NAME, description=DESCRIPTION, agent=build_agent(read_env(ENV_FILE)))
