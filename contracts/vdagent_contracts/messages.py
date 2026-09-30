"""Requests between agents (system prompt §6.1).

A message that starts with `{` and parses as JSON is a contract request and is validated strictly; anything else
is a free-text question from the user (or another agent), handled by the receiving agent's own fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vdagent_contracts.envelope import ArtifactRef
from vdagent_contracts.scope import UserContext

FROZEN = ConfigDict(extra="forbid", frozen=True)

_FROM_PREFIX = re.compile(r"^\[from: [^\]]+\]\s*")


@dataclass(frozen=True)
class ContractMessage:
    contract: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FreeText:
    text: str


def parse_incoming(message: str) -> ContractMessage | FreeText:
    """Classify an incoming message; JSON without a `contract` field raises ValueError."""
    text = _FROM_PREFIX.sub("", message, count=1).strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return FreeText(text=text)
        if not isinstance(data, dict) or not isinstance(data.get("contract"), str):
            raise ValueError("JSON request without a `contract` field")
        return ContractMessage(contract=data["contract"], data=data)
    return FreeText(text=text)


class AnsweredChoice(BaseModel):
    model_config = FROZEN

    input_id: str
    choice: str


class StepSpec(BaseModel):
    """One plan step sent by the Orchestrator (R-03 idempotency key, R-06 snapshot, R-08 deadline in seconds)."""

    model_config = FROZEN

    contract: Literal["StepSpec@1"] = "StepSpec@1"
    run_id: str
    plan_id: str
    step_id: str = Field(pattern=r"^B[1-9][0-9]*$")
    idempotency_key: str
    operation: str
    spec: dict[str, Any] = Field(default_factory=dict)
    user_context: UserContext
    snapshot_id: str | None = None
    semantic_config_version: str | None = None
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    released_inputs: list[str] = Field(default_factory=list)  # input steps the orchestrator says to run without
    answered_choices: list[AnsweredChoice] = Field(default_factory=list)  # DEC-027
    deadline_s: int = Field(default=120, gt=0)
    original_question: str

    @model_validator(mode="after")
    def _key_matches(self) -> StepSpec:
        if self.idempotency_key != f"{self.plan_id}:{self.step_id}":
            raise ValueError("idempotency_key must be plan_id:step_id")
        return self
