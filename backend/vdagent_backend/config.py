"""Backend configuration: `backend/config.yaml` + `VDAGENT_*` env overrides.

- `VDAGENT_CONFIG` selects the YAML file (default: `backend/config.yaml` next to this package).
- The Backend's `.env` is loaded first: the nearest `.env` walking up from the config file — so
  `backend/.env` for the default config — else one found from the working directory. The process
  environment wins over it.
- Every scalar field of `Config` can be overridden by `VDAGENT_<KEY>` (e.g. `VDAGENT_BACKEND_DB`,
  `VDAGENT_MAX_STEPS`).
- Relative paths are resolved against the current working directory.
- `plugins:` is the ordered list of agent plugins; each entry is `{module, opts, enabled,
  mcp_tools}`. Unknown top-level keys are ignored; a malformed plugin entry is a `ValueError`
  naming the entry.

May import: `core`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_type_hints

import yaml
from dotenv import find_dotenv, load_dotenv

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class PluginSpec:
    """One `plugins:` entry.

    Attributes:
        module: The module to import; it must export `setup(api, opts)`.
        opts: The dict handed to `setup` (a copy).
        enabled: False skips the entry without importing it.
        mcp_tools: MCP tool names granted to every agent this plugin registers.
    """

    module: str
    opts: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    mcp_tools: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Config:
    """The Backend configuration; every scalar field can be overridden by `VDAGENT_<FIELD>`."""

    backend_db: str
    warehouse_db: str
    mcp_public_url: str
    frontend_dist: str
    max_depth: int = 4
    max_steps: int = 12
    plugins: list[PluginSpec] = field(default_factory=list)


_PLUGIN_KEYS = frozenset({"module", "opts", "enabled", "mcp_tools"})


def _scalars() -> dict[str, type]:
    """`Config` fields of type `str` or `int`, with that type (the keys `VDAGENT_*` can override)."""
    hints = get_type_hints(Config)
    return {f.name: hints[f.name] for f in fields(Config) if hints[f.name] in (str, int)}


def _load_env_file(cfg_path: Path) -> None:
    for directory in cfg_path.resolve().parents:
        candidate = directory / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return
    found = find_dotenv(usecwd=True)
    if found:
        load_dotenv(found, override=False)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Read the YAML config (after loading the Backend's `.env`) and apply `VDAGENT_*` overrides."""
    cfg_path = Path(path or os.environ.get("VDAGENT_CONFIG") or DEFAULT_CONFIG_PATH)
    _load_env_file(cfg_path)
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    values: dict[str, object] = {}
    for key, typ in _scalars().items():
        env = os.environ.get(f"VDAGENT_{key.upper()}")
        value = env if env is not None else raw.get(key)
        if value is not None:
            values[key] = typ(value)
    return Config(plugins=parse_plugins(raw.get("plugins")), **values)  # type: ignore[arg-type]


def parse_plugins(raw: object) -> list[PluginSpec]:
    """The `plugins:` value as specs, in list order.

    Raises:
        ValueError: An entry is malformed; the message names it (`plugins[<i>]…`).
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("plugins must be a list of {module, opts, enabled, mcp_tools} entries")
    specs: list[PluginSpec] = []
    for i, entry in enumerate(raw):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        where = f"plugins[{i}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a mapping with a `module` key")
        unknown = sorted(str(k) for k in entry if k not in _PLUGIN_KEYS)  # pyright: ignore[reportUnknownVariableType]
        if unknown:
            raise ValueError(f"{where} has unknown keys: {', '.join(unknown)}")
        module = entry.get("module")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(module, str) or not module.strip():
            raise ValueError(f"{where}.module must be a non-empty string")
        opts = entry.get("opts", {})  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if opts is None:
            opts = {}
        if not isinstance(opts, dict):
            raise ValueError(f"{where}.opts must be a mapping")
        enabled = entry.get("enabled", True)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(enabled, bool):
            raise ValueError(f"{where}.enabled must be true or false")
        tools = entry.get("mcp_tools", [])  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(tools, list) or not all(isinstance(t, str) and t.strip() for t in tools):  # pyright: ignore[reportUnknownVariableType]
            raise ValueError(f"{where}.mcp_tools must be a list of non-empty strings")
        specs.append(
            PluginSpec(
                module=module.strip(),
                opts=dict(opts),  # pyright: ignore[reportUnknownArgumentType]
                enabled=enabled,
                mcp_tools=frozenset(t.strip() for t in tools),  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            )
        )
    return specs
