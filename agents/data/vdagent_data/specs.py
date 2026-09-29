"""Operation specs (build spec 02 §3) as Pydantic models; names are checked against the semantic layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vdagent_data.semantic.loader import LAYER

FROZEN = ConfigDict(extra="forbid", frozen=True)


def _known(values: list[str], vocabulary: dict[str, object], what: str) -> list[str]:
    unknown = [v for v in values if v not in vocabulary]
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)}")
    return values


class Mention(BaseModel):
    model_config = FROZEN
    text: str
    kind_hint: Literal["PROJECT", "ZONE", "UNIT", "UNKNOWN"] = "UNKNOWN"


class Scope(BaseModel):
    model_config = FROZEN
    mentions: list[Mention] = Field(default_factory=list)
    scope_all: bool = False


class Acceptance(BaseModel):
    model_config = FROZEN
    grain: str | None = None
    min_rows: int | None = None


class CommonSpec(BaseModel):
    model_config = FROZEN
    objective: str = Field(max_length=300)
    scope: Scope
    filters: list[str] = Field(default_factory=list)
    extra_needs: list[str] = Field(default_factory=list)
    acceptance: Acceptance = Field(default_factory=Acceptance)

    @field_validator("filters")
    @classmethod
    def _filters(cls, v: list[str]) -> list[str]:
        return _known(v, LAYER.filters, "filter")


class FetchUnitsSpec(CommonSpec):
    attributes: list[str] = Field(default_factory=list)

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, v: list[str]) -> list[str]:
        return _known(v, LAYER.attributes, "attribute")


class AggregateMetricsSpec(CommonSpec):
    metrics: list[str] = Field(min_length=1)
    group_by: list[str] = Field(default_factory=list)

    @field_validator("metrics")
    @classmethod
    def _metrics(cls, v: list[str]) -> list[str]:
        return _known(v, LAYER.metrics, "metric")

    @field_validator("group_by")
    @classmethod
    def _group_by(cls, v: list[str]) -> list[str]:
        return _known(v, LAYER.dimensions, "dimension")


class FetchPeerCandidatesSpec(CommonSpec):
    target_unit: Mention


Context = Literal["price_history", "funnel", "secondary_comps", "macro", "infrastructure"]


class FetchUnitContextSpec(CommonSpec):
    unit_set_package_id: str
    contexts: list[Context] = Field(min_length=1)


OPERATIONS: dict[str, type[CommonSpec]] = {
    "fetch_units": FetchUnitsSpec,
    "aggregate_metrics": AggregateMetricsSpec,
    "fetch_peer_candidates": FetchPeerCandidatesSpec,
    "fetch_unit_context": FetchUnitContextSpec,
}
