"""Compare plugin entry point. VHOP demo mode runs without a model key."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vdagent_sdk import PluginAPI


def read_env() -> dict[str, str]:
    from .settings import read_env as load

    return load()


def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None:
    if opts.get("vhop_demo"):
        from .vh_chat import DemoAgent

        api.register_agent(
            name="compare",
            description="So sánh căn hộ VHOP: nhóm tương đồng, hai căn, cohort, ranking.",
            agent=DemoAgent(),
        )
        return
    from .agent import DESCRIPTION, NAME, build_agent

    api.register_agent(name=NAME, description=DESCRIPTION, agent=build_agent(read_env()))