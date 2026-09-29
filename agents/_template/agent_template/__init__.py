"""vdagent agent plugin built from `agents/_template/` (see the folder's README.md).

The Backend imports this module (listed under `plugins:` in `backend/config.yaml`) and calls
`setup(api, opts)` once at startup. Register your agent(s) here; read configuration and construct
clients here too, and raise `PluginConfigError` for bad settings (the plugin is then skipped).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vdagent_sdk import PluginAPI

from .agent import DESCRIPTION, EchoAgent

DEFAULT_NAME = "echo"


def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None:
    api.register_agent(name=str(opts.get("name", DEFAULT_NAME)), description=DESCRIPTION, agent=EchoAgent())
