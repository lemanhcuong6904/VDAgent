"""Load and query the semantic layer (build spec 02 §4): whitelist, JOIN graph, synonyms, metrics, filters."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

LAYER_PATH = Path(__file__).resolve().parent / "layer.yaml"
FROZEN = ConfigDict(extra="forbid", frozen=True)

TermKind = Literal["metric", "dimension", "filter"]


def normalize(text: str) -> str:
    """Lower case, no diacritics (đ → d), single spaces: for synonym and value matching."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().replace("_", " ").split())


class Dimension(BaseModel):
    model_config = FROZEN
    column: str
    description: str
    synonyms: list[str] = Field(default_factory=list)


class Filter(BaseModel):
    model_config = FROZEN
    sql: str
    description: str
    synonyms: list[str] = Field(default_factory=list)


class Metric(BaseModel):
    model_config = FROZEN
    formula_id: str
    description: str
    synonyms: list[str] = Field(default_factory=list)
    numerator: str
    denominator: str | None
    unit: Literal["RATIO", "DAY", "COUNT", "VND", "VND_PER_M2", "PCT"]
    min_n: int = 1


class Attribute(BaseModel):
    model_config = FROZEN
    column: str
    description: str


class ForbiddenJoin(BaseModel):
    model_config = FROZEN
    from_: str = Field(alias="from")
    to: str
    fix: str


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    semantic_version: str
    dw_version: str
    tables: dict[str, list[str]]
    snapshot_tables: list[str]
    rbac: dict[str, str]
    joins: list[tuple[str, str]]
    join_forbidden: list[ForbiddenJoin]
    base: str
    dimensions: dict[str, Dimension]
    filters: dict[str, Filter]
    metrics: dict[str, Metric]
    attributes: dict[str, Attribute]

    def _edges(self) -> set[frozenset[str]]:
        return {frozenset((a.split(".")[0], b.split(".")[0])) for a, b in self.joins}

    def join_allowed(self, left: str, right: str) -> bool:
        return left == right or frozenset((left, right)) in self._edges()

    def join_fix(self, left: str, right: str) -> str | None:
        for rule in self.join_forbidden:
            if {rule.from_, rule.to} == {left, right}:
                return rule.fix
        return None

    def lookup(self, term: str) -> tuple[TermKind, str] | None:
        """Map a business word (any accents/case) or a layer name to (kind, name)."""
        wanted = normalize(term)
        groups: list[tuple[TermKind, dict[str, Dimension] | dict[str, Filter] | dict[str, Metric]]] = [
            ("metric", self.metrics), ("filter", self.filters), ("dimension", self.dimensions)
        ]
        for kind, entries in groups:
            for name, entry in entries.items():
                if wanted == normalize(name) or wanted in {normalize(s) for s in entry.synonyms}:
                    return kind, name
        return None


def load_layer(path: Path = LAYER_PATH) -> Layer:
    return Layer.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


LAYER = load_layer()
