"""The plugin entry of the Insight Agent v2: `setup(api, opts)` registers the bridge agent (`bridge.InsightAgent`)
under the bridge's `NAME` / `DESCRIPTION`, built from the plugin env; `read_env` reads that env without touching
`os.environ`.

The agent's own behaviour (deterministic pipeline, TEMPLATE / LLM narration) is covered by test_bridge.py and
test_run_task.py; this file only covers the public plugin API."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from vdagent_sdk import Agent, PluginConfigError

import vdagent_insight
from vdagent_insight import agent as pipeline
from vdagent_insight import bridge, setup
from vdagent_insight.settings import read_env


@dataclass
class FakeAPI:
    agents: dict[str, tuple[str, Agent]] = field(default_factory=dict)
    plugin: str = "test"
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("test.insight"))

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        self.agents[name] = (description, agent)

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        raise AssertionError("this plugin registers no shutdown hook")


def offline_env(tmp_path: Path, **over: str) -> dict[str, str]:
    """TEMPLATE mode on the bundled fixtures, with a store of its own (no network, no repo var/)."""
    return {"INSIGHT_LLM": "off", "INSIGHT_ARTIFACT_SOURCE": "fixtures", "INSIGHT_STORE_PATH": str(tmp_path / "insight.db"), **over}


def test_setup_registers_the_bridge_agent_under_its_name_and_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(vdagent_insight, "read_env", lambda: offline_env(tmp_path))
    api = FakeAPI()
    with caplog.at_level(logging.INFO, logger="test.insight"):
        setup(api, {})
    ((name, (description, agent)),) = api.agents.items()
    assert (name, description) == (bridge.NAME, bridge.DESCRIPTION) and isinstance(agent, bridge.InsightAgent)
    assert "insight: data source fixtures, LLM off (TEMPLATE)" in caplog.text


def test_description_has_one_canonical_definition_exported_by_the_package() -> None:
    assert vdagent_insight.DESCRIPTION is bridge.DESCRIPTION and vdagent_insight.NAME == bridge.NAME == "insight"
    assert not hasattr(pipeline, "DESCRIPTION")  # the pipeline module does not keep a second copy


def test_setup_fails_naming_the_bad_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vdagent_insight, "read_env", lambda: offline_env(tmp_path, INSIGHT_ARTIFACT_SOURCE="warehouse"))
    with pytest.raises(PluginConfigError, match="INSIGHT_ARTIFACT_SOURCE"):
        setup(FakeAPI(), {})


def test_read_env_prefers_the_plugin_env_file_and_never_writes_os_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=from-file\nINSIGHT_LLM=\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-process")
    monkeypatch.setenv("GEMINI_API_KEY", "process-gemini")
    env = read_env(env_file)
    assert (env["OPENAI_API_KEY"], env["GEMINI_API_KEY"], env["INSIGHT_LLM"]) == ("from-file", "process-gemini", "")
    assert os.environ["OPENAI_API_KEY"] == "from-process"
    assert read_env(tmp_path / "missing.env")["OPENAI_API_KEY"] == "from-process"
