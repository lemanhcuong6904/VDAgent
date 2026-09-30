"""Catalogs of the worker agents, as plain data both the agents and the Orchestrator import (DEC-023).

`<agent>.json` is the frozen catalog an agent generates (the agent's own test keeps it in sync); an agent without
one falls back to its stub in `stubs.py` (fixture, DEC-020).
"""

from __future__ import annotations

import json
from pathlib import Path

from vdagent_contracts.catalog import AgentCatalog

_DIR = Path(__file__).resolve().parent
WORKER_AGENTS = ("data", "compare", "insight", "chart", "report")


def load_catalog(agent: str) -> AgentCatalog:
    frozen = _DIR / f"{agent}.json"
    if frozen.is_file():
        return AgentCatalog.model_validate(json.loads(frozen.read_text(encoding="utf-8")))
    from vdagent_contracts.catalogs.stubs import STUB_CATALOGS

    return STUB_CATALOGS[agent]


def load_all() -> dict[str, AgentCatalog]:
    return {agent: load_catalog(agent) for agent in WORKER_AGENTS}
