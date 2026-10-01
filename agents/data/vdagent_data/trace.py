"""The working trace of a Data step: what the agent really did, as structured events (no prose).

`run_step` reports each real action to an optional `Observer`. An event says which stage it is (`intake`, `scope`,
`snapshot`, `config`, `read`, `check`, `write`, `done`, `fail`), whether it is a one-off `note` or the `start` / `end`
of a call to the warehouse or the artifact store, why the agent does it (`purpose`, declared once at the call site) and
the facts of that moment, read from the run itself. Facts are metadata only (table, rows, hash, ids, codes, dates):
never row values, so a narrator can turn the trace into natural language without any hardcoded result and without
seeing the data (SPEC §3.5: the model sees metadata and profile, not rows).

Nothing here changes what the step computes: an observer that is missing or breaks never affects the report.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

Scalar = str | int | float | bool | None
Fact = Scalar | list[Scalar]
MAX_TEXT = 300  # longest string kept in a fact: the trace is a summary, not a copy of the request


@dataclass(frozen=True)
class TraceEvent:
    stage: str
    state: Literal["note", "start", "end"]
    call_id: str | None  # ties a `start` to its `end`; None for a `note`
    purpose: str  # why the agent does this, in one line (Vietnamese, for the person reading the trace)
    facts: Mapping[str, Fact] = field(default_factory=dict)
    phase: str = ""  # the pipeline phase the event belongs to (intake, snapshot, resolve, fetch, funnel, check, write, done, fail)


class Observer(Protocol):
    async def emit(self, event: TraceEvent) -> None:
        """Receive one event. May be slow (a narrator): the step waits for it; failures are ignored."""
        ...


def _scalar(value: Any) -> Scalar:
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)[:MAX_TEXT]


def clean_facts(facts: Mapping[str, Any]) -> dict[str, Fact]:
    """Only scalars and lists of scalars survive; a mapping becomes `key=value` strings, anything else its text."""
    out: dict[str, Fact] = {}
    for key, value in facts.items():
        if isinstance(value, Mapping):
            out[key] = [f"{k}={_scalar(v)}" for k, v in value.items()]
        elif isinstance(value, list | tuple | set | frozenset):
            out[key] = [_scalar(v) for v in (sorted(value, key=str) if isinstance(value, set | frozenset) else value)]
        else:
            out[key] = _scalar(value)
    return out


class Tracer:
    """Numbers the calls of one run and hands events to the observer; a broken observer is logged and ignored."""

    def __init__(self, observer: Observer | None = None) -> None:
        self._observer = observer
        self._n = 0
        self._purpose: dict[str, str] = {}
        self.phase = ""

    def enter(self, phase: str) -> None:
        """The pipeline moves to `phase`: every event from now on belongs to it."""
        self.phase = phase

    async def note(self, stage: str, purpose: str, **facts: Any) -> None:
        await self._send(TraceEvent(stage, "note", None, purpose, clean_facts(facts), self.phase))

    async def start(self, stage: str, purpose: str, **facts: Any) -> str:
        self._n += 1
        call_id = f"c{self._n}"
        self._purpose[call_id] = purpose
        await self._send(TraceEvent(stage, "start", call_id, purpose, clean_facts(facts), self.phase))
        return call_id

    async def end(self, stage: str, call_id: str, **facts: Any) -> None:
        await self._send(TraceEvent(stage, "end", call_id, self._purpose.pop(call_id, ""), clean_facts(facts), self.phase))

    async def _send(self, event: TraceEvent) -> None:
        if self._observer is None:
            return
        try:
            await self._observer.emit(event)
        except Exception:  # never CancelledError: cancellation passes through
            log.warning("data: the trace observer failed on %s/%s", event.stage, event.state, exc_info=True)
