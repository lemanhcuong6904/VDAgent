"""App composition: startup checks that need no running lifespan."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_config
from vdagent_backend.app import create_app
from vdagent_backend.config import PluginSpec


def test_an_unknown_granted_tool_fails_startup_naming_the_entry_and_the_tool(tmp_path: Path) -> None:
    specs = [PluginSpec("p_ok", mcp_tools=frozenset({"run_query"})), PluginSpec("p_typo", mcp_tools=frozenset({"run_qeury"}))]
    with pytest.raises(ValueError, match=r"p_typo.*'run_qeury'"):
        create_app(make_config(tmp_path, plugins=specs))


def test_disabled_entries_are_not_checked(tmp_path: Path) -> None:
    spec = PluginSpec("p_off", enabled=False, mcp_tools=frozenset({"run_qeury"}))
    create_app(make_config(tmp_path, plugins=[spec]))
