"""VDAgent Chart Agent plugin package."""

from collections.abc import Mapping
from typing import Any

from vdagent_sdk import PluginAPI

from .agent import ChartPluginAgent, DESCRIPTION, NAME
from .fixture_store import FixtureArtifactStore
from .llm import OpenAIVisualReasoner, VisualReasoner
from .service import ChartAgentService
from .settings import load_settings, read_env
from .errors import ChartError


def make_reasoner(env: Mapping[str, str]) -> VisualReasoner | None:
    """Enable the optional GPT advisor only with a complete local config."""
    try:
        return OpenAIVisualReasoner(load_settings(env))
    except ChartError:
        return None


def demo_enabled(env: Mapping[str, str], opts: Mapping[str, Any]) -> bool:
    """Demo commands (pinned demo artifacts, synthetic `chart ask` upstream) only when explicitly enabled (D6)."""
    return opts.get("demo") is True or (env.get("CHART_DEMO") or "").strip().lower() in ("on", "1", "true")


def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None:
    """Production default: StepSpec@1 `draw_chart` over real artifacts only; the demo store is not even loaded."""
    env = read_env()
    reasoner = make_reasoner(env)
    demo = demo_enabled(env, opts)
    service = ChartAgentService(FixtureArtifactStore.demo() if demo else FixtureArtifactStore([]), reasoner=reasoner)
    api.register_agent(name=NAME, description=DESCRIPTION,
                       agent=ChartPluginAgent(service, upstream_reasoner=reasoner, demo_enabled=demo))
