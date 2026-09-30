"""ArtifactEnvelope: the shared wrapper of every artifact in the Artifact Store (system prompt §6.2, D5).

Envelope fields are snake_case; `payload` keeps the field names of the producing agent's spec.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vdagent_contracts.canonical import content_hash

FROZEN = ConfigDict(extra="forbid", frozen=True)


class ArtifactStatus(StrEnum):
    DRAFT = "DRAFT"
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class ArtifactType(StrEnum):
    DATA_PACKAGE = "data_package"
    METRIC = "metric"
    DQ = "dq"
    DATASET = "dataset"
    MARKET_CONTEXT = "market_context"
    PEER_DEFINITION = "peer_definition"
    COMPARISON = "comparison"
    INSIGHT = "insight"
    CHART_SPEC = "chart_spec"
    REPORT = "report"
    RUN_SUMMARY = "run_summary"
    RUN_STATE = "run_state"


class Producer(BaseModel):
    model_config = FROZEN

    agent: str
    agent_version: str
    prompt_version: str | None = None
    model_id: str | None = None

    @property
    def label(self) -> str:
        return f"{self.agent}@{self.agent_version}"


class ArtifactRef(BaseModel):
    model_config = FROZEN

    artifact_id: str
    version: int = Field(ge=1)
    artifact_type: ArtifactType
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    """Expected `content_hash` of the pinned version; when set, the store rejects a reference that does not match."""


# Excluded from the content hash besides the canonical run-identity fields: the owner is not content.
_NOT_CONTENT = {"user_id"}


class ArtifactEnvelope(BaseModel):
    model_config = FROZEN

    artifact_id: str
    run_id: str
    task_id: str
    user_id: str
    artifact_type: ArtifactType
    schema_version: str
    version: int = Field(default=1, ge=1)
    status: ArtifactStatus
    producer: Producer
    content_hash: str | None = None
    snapshot_refs: list[str] = Field(default_factory=list)
    semantic_config_version: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    input_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reason_code: str | None = None
    reason: str | None = None
    payload: dict[str, Any]
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _partial_needs_limitations(self) -> ArtifactEnvelope:
        if self.status is ArtifactStatus.PARTIAL and not self.limitations:
            raise ValueError("a PARTIAL artifact must list its limitations")
        return self

    def compute_content_hash(self) -> str:
        """Hash of the content: run identity (canonical.RUN_IDENTITY_FIELDS) and owner excluded."""
        return content_hash(self.model_dump(mode="python", exclude=_NOT_CONTENT))


class ArtifactDraft(BaseModel):
    """What a producer submits; the store adds run identity, version, content_hash and created_at.

    `artifact_id` set = a new version of that artifact (the old version becomes SUPERSEDED).
    """

    model_config = FROZEN

    artifact_id: str | None = None
    artifact_type: ArtifactType
    schema_version: str
    status: ArtifactStatus
    producer: Producer
    snapshot_refs: list[str] = Field(default_factory=list)
    semantic_config_version: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    input_artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reason_code: str | None = None
    reason: str | None = None
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _checks(self) -> ArtifactDraft:
        if self.status is ArtifactStatus.SUPERSEDED:
            raise ValueError("SUPERSEDED is set by the store, never submitted")
        if self.status is ArtifactStatus.PARTIAL and not self.limitations:
            raise ValueError("a PARTIAL artifact must list its limitations")
        if len(self.snapshot_refs) > 1:
            raise ValueError("an artifact is built from at most one snapshot")
        return self
