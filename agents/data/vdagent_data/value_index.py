"""Value index (build spec 02 §8 C4): project, zone and unit names the user may see, matched exactly, without accents,
by whole words, then fuzzily. Built from the scoped DW, so names outside the user's scope do not exist here.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from vdagent_agentkit.mcp_client import McpSession
from vdagent_data.semantic.loader import normalize

KINDS = ("PROJECT", "ZONE", "UNIT")
FUZZY_MATCH = 0.85
FUZZY_SUGGEST = 0.5


@dataclass(frozen=True)
class Option:
    id: str
    label: str


@dataclass(frozen=True)
class Match:
    kind: str
    ids: list[str]
    label: str


@dataclass(frozen=True)
class Ambiguous:
    kind: str
    options: list[Option]


@dataclass(frozen=True)
class NotFound:
    suggestions: list[Option] = field(default_factory=list)


@dataclass(frozen=True)
class Entry:
    kind: str
    id: str
    label: str

    @property
    def key(self) -> str:
        text = normalize(self.label)
        return re.sub(r"[^a-z0-9]", "", text) if self.kind == "UNIT" else text


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _unit_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize(text))


@dataclass
class ValueIndex:
    entries: list[Entry]

    def _pool(self, kind_hint: str) -> list[Entry]:
        return [e for e in self.entries if kind_hint in ("UNKNOWN", e.kind)]

    def get(self, entity_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entity_id), None)

    def resolve(self, text: str, kind_hint: str = "UNKNOWN") -> Match | Ambiguous | NotFound:
        pool = self._pool(kind_hint)
        wanted, wanted_unit = normalize(text), _unit_key(text)
        exact = [e for e in pool if e.key == (wanted_unit if e.kind == "UNIT" else wanted)]
        if len(exact) == 1:
            return self._match(exact)
        words = [e for e in pool if e.kind != "UNIT" and re.search(rf"\b{re.escape(wanted)}\b", e.key)]
        candidates = exact or words
        if not candidates:
            scored = sorted(((difflib.SequenceMatcher(None, wanted, e.key).ratio(), e) for e in pool),
                            key=lambda t: (-t[0], t[1].label))
            # numbers identify buildings and units: a typo may be forgiven, a different number never
            candidates = [e for score, e in scored if score >= FUZZY_MATCH and _digits(e.key) == _digits(wanted)]
            if not candidates:
                return NotFound([Option(e.id, e.label) for score, e in scored[:3] if score >= FUZZY_SUGGEST])
        if len(candidates) == 1:
            return self._match(candidates)
        ordered = sorted(candidates, key=lambda e: e.label)
        return Ambiguous(kind=ordered[0].kind, options=[Option(e.id, e.label) for e in ordered[:3]])

    @staticmethod
    def _match(entries: list[Entry]) -> Match:
        return Match(kind=entries[0].kind, ids=[entries[0].id], label=entries[0].label)


async def _rows(session: McpSession, sql: str) -> list[list[Any]]:
    outcome = await session.call_tool("re_run_query", {"sql": sql})
    if outcome.is_error:
        raise RuntimeError(outcome.text)
    result = json.loads(outcome.text)
    rows = list(result["preview"])
    while len(rows) < result["row_count"]:
        page = await session.call_tool(
            "get_dataset_rows", {"dataset_id": result["dataset_id"], "offset": len(rows), "limit": 200}
        )
        rows.extend(json.loads(page.text)["rows"])
    return rows


async def load_index(session: McpSession) -> ValueIndex:
    entries = [Entry("PROJECT", k, n) for k, n in await _rows(session, "SELECT project_key, project_name FROM dim_project_profile")]
    entries += [Entry("ZONE", k, n) for k, n in await _rows(session, "SELECT zone_key, zone_name FROM dim_zone_master")]
    entries += [Entry("UNIT", k, c) for k, c in await _rows(session, "SELECT unit_key, unit_code FROM dim_unit_master")]
    return ValueIndex(entries)
