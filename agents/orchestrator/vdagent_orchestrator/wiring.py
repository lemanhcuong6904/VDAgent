"""Wiring (build spec 01 §6.3, pure): HARD/SOFT waits from catalog kinds, consumer lists, snapshot pin.

Under D3 the Orchestrator dispatches in waves, so `forward_to` is the list of steps that consume a step's packages
(the dispatcher hands them over); agents never forward to each other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vdagent_orchestrator.catalogs import CatalogRegistry


class WaitEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: str
    mode: Literal["HARD", "SOFT"]
    artifact_kinds: list[str] = Field(default_factory=list)
    snapshot_only: bool = False


@dataclass(frozen=True)
class Node:
    step_id: str
    agent: str
    operation: str
    inputs: tuple[str, ...]


def step_no(step_id: str) -> int:
    return int(step_id[1:])


def wire(nodes: Sequence[Node], registry: CatalogRegistry, *, snapshot_pinned: bool,
         known_produces: Mapping[str, Sequence[str]] = {}) -> tuple[dict[str, list[WaitEntry]], dict[str, list[str]]]:
    """Waits and consumer lists for `nodes`; `known_produces` gives kinds of steps outside `nodes` (earlier plans).
    Unknown inputs or operations are left to the checker (BAD_WIRING / UNKNOWN_OPERATION)."""
    produces: dict[str, set[str]] = {k: set(v) for k, v in known_produces.items()}
    agents = {n.step_id: n.agent for n in nodes}
    for n in nodes:
        try:
            produces[n.step_id] = set(registry.operation(n.agent, n.operation).produces)
        except KeyError:
            produces[n.step_id] = set()
    waits: dict[str, list[WaitEntry]] = {n.step_id: [] for n in nodes}
    forwards: dict[str, set[str]] = {n.step_id: set() for n in nodes}
    for n in nodes:
        try:
            op = registry.operation(n.agent, n.operation)
        except KeyError:
            continue
        for p in n.inputs:
            if p not in produces:
                continue
            kinds = produces[p] & (set(op.requires) | set(op.uses_if_present))
            hard = bool(kinds & set(op.requires))
            waits[n.step_id].append(WaitEntry(step_id=p, mode="HARD" if hard else "SOFT", artifact_kinds=sorted(kinds)))
            forwards.setdefault(p, set()).add(n.step_id)
    if not snapshot_pinned:
        data = sorted((n for n in nodes if n.agent == "data"), key=lambda n: step_no(n.step_id))
        open_data = [n for n in data if not waits[n.step_id]]
        if open_data:
            pin = open_data[0].step_id
            for n in data:
                if n.step_id != pin and not any(agents.get(w.step_id) == "data" for w in waits[n.step_id]):
                    waits[n.step_id].append(WaitEntry(step_id=pin, mode="SOFT", snapshot_only=True))
                    forwards[pin].add(n.step_id)
    return waits, {k: sorted(v, key=step_no) for k, v in forwards.items()}


__all__ = ["Node", "WaitEntry", "step_no", "wire"]
