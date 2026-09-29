"""Backend configuration: `backend/config.yaml` + `VDAGENT_*` env overrides.

- `VDAGENT_CONFIG` selects the YAML file (default: `backend/config.yaml` next to this package).
- The Backend's `.env` is loaded first: the nearest `.env` walking up from the config file — so
  `backend/.env` for the default config — else one found from the working directory. The process
  environment wins over it.
- Scalar keys can be overridden by `VDAGENT_<KEY>` (e.g. `VDAGENT_BACKEND_DB`, `VDAGENT_MAX_STEPS`).
- Relative paths are resolved against the current working directory.
- `plugins:` is the ordered list of agent plugins (plugins spec §4.1); unknown top-level keys are
  ignored, malformed plugin entries are a `ValueError` naming the entry.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class PluginSpec:
    """One `plugins:` entry: the module to import, the dict handed to its `setup`, and a toggle."""

    module: str
    opts: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    backend_db: str
    warehouse_db: str
    mcp_public_url: str
    frontend_dist: str
    max_depth: int = 4
    max_steps: int = 12
    plugins: list[PluginSpec] = field(default_factory=list)


_SCALARS: dict[str, type] = {
    "backend_db": str,
    "warehouse_db": str,
    "mcp_public_url": str,
    "frontend_dist": str,
    "max_depth": int,
    "max_steps": int,
}

_PLUGIN_KEYS = frozenset({"module", "opts", "enabled"})


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
    cfg_path = Path(path or os.environ.get("VDAGENT_CONFIG") or DEFAULT_CONFIG_PATH)
    _load_env_file(cfg_path)
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    values: dict[str, object] = {}
    for key, typ in _SCALARS.items():
        env = os.environ.get(f"VDAGENT_{key.upper()}")
        value = env if env is not None else raw.get(key)
        if value is not None:
            values[key] = typ(value)
    return Config(plugins=_parse_plugins(raw.get("plugins")), **values)  # type: ignore[arg-type]


def _parse_plugins(raw: object) -> list[PluginSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("plugins must be a list of {module, opts, enabled} entries")
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
        specs.append(PluginSpec(module=module.strip(), opts=dict(opts), enabled=enabled))  # pyright: ignore[reportUnknownArgumentType]
    return specs
