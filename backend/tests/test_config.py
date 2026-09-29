"""Backend configuration: the `plugins:` spec list (plugins spec §4.1) and `.env` loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from vdagent_backend.config import PluginSpec, load_config

BASE = """\
backend_db: ./var/backend.db
warehouse_db: ./var/warehouse.db
mcp_public_url: http://localhost:8000/mcp
frontend_dist: ./frontend/dist
"""


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # setenv first so monkeypatch restores "unset" even when load_dotenv sets the variable later.
    for var in ("VDAGENT_MAX_STEPS", "VDAGENT_MCP_PUBLIC_URL"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "repo" / "backend" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(BASE)
    return path


def _with(cfg_file: Path, extra: str) -> Path:
    cfg_file.write_text(BASE + extra)
    return cfg_file


def test_plugins_keep_list_order_and_default_opts_and_enabled(cfg_file: Path) -> None:
    cfg = load_config(
        _with(
            cfg_file,
            """\
plugins:
  - module: vdagent_orchestrator
  - module: vdagent_data
    opts: {model: small, n: 2}
  - module: vdagent_report
    enabled: false
""",
        )
    )
    assert cfg.plugins == [
        PluginSpec("vdagent_orchestrator"),
        PluginSpec("vdagent_data", opts={"model": "small", "n": 2}),
        PluginSpec("vdagent_report", enabled=False),
    ]
    assert cfg.plugins[0].opts == {} and cfg.plugins[0].enabled is True


def test_missing_plugins_key_means_no_plugins_and_stale_hub_keys_are_ignored(cfg_file: Path) -> None:
    cfg = load_config(_with(cfg_file, "agent_listen: 127.0.0.1:50050\nagents:\n  data: {description: x}\n"))
    assert cfg.plugins == []


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("plugins: {module: x}\n", "plugins must be a list"),
        ("plugins:\n  - vdagent_data\n", "plugins[0] must be a mapping"),
        ("plugins:\n  - {opts: {}}\n", "plugins[0].module must be a non-empty string"),
        ("plugins:\n  - {module: a}\n  - {module: ''}\n", "plugins[1].module must be a non-empty string"),
        ("plugins:\n  - {module: a, opts: [1]}\n", "plugins[0].opts must be a mapping"),
        ("plugins:\n  - {module: a, enabled: 'no'}\n", "plugins[0].enabled must be true or false"),
        ("plugins:\n  - {module: a, name: b}\n", "plugins[0] has unknown keys: name"),
    ],
    ids=["not-list", "not-mapping", "no-module", "empty-module", "opts", "enabled", "unknown-key"],
)
def test_malformed_plugin_entries_are_rejected_naming_the_entry(cfg_file: Path, extra: str, message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        load_config(_with(cfg_file, extra))


def test_backend_env_file_is_loaded_but_process_env_wins(cfg_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (cfg_file.parent / ".env").write_text("VDAGENT_MAX_STEPS=7\nVDAGENT_MCP_PUBLIC_URL=http://from-file/mcp\n")
    monkeypatch.setenv("VDAGENT_MCP_PUBLIC_URL", "http://from-process/mcp")
    cfg = load_config(cfg_file)
    assert (cfg.max_steps, cfg.mcp_public_url) == (7, "http://from-process/mcp")


def test_mcp_tools_is_an_optional_set_of_tool_names(cfg_file: Path) -> None:
    cfg = load_config(
        _with(cfg_file, "plugins:\n  - module: a\n    mcp_tools: [run_query, list_tables, run_query]\n  - module: b\n")
    )
    assert cfg.plugins[0].mcp_tools == frozenset({"run_query", "list_tables"})
    assert cfg.plugins[1].mcp_tools == frozenset()


@pytest.mark.parametrize(
    "value",
    ["run_query", "{run_query: true}", "[run_query, '']", "[run_query, 3]"],
    ids=["string", "mapping", "empty-entry", "non-string-entry"],
)
def test_malformed_mcp_tools_are_rejected_naming_the_entry(cfg_file: Path, value: str) -> None:
    with pytest.raises(ValueError, match=r"plugins\[1\]\.mcp_tools must be a list of non-empty strings"):
        load_config(_with(cfg_file, f"plugins:\n  - module: a\n  - module: b\n    mcp_tools: {value}\n"))
