"""AgentReport: what every agent returns to its caller (system prompt §6.1).

The final assistant step of an agent is 1–3 Vietnamese summary lines followed by exactly one ```json fence holding
an AgentReport. A report that does not parse is FATAL for the Orchestrator.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vdagent_contracts.envelope import ArtifactRef

FROZEN = ConfigDict(extra="forbid", frozen=True)

ReportState = Literal["completed", "input_required", "failed", "rejected", "canceled"]


class ReportError(BaseModel):
    model_config = FROZEN

    code: str
    message: str
    retryable: bool = False


class QuestionOption(BaseModel):
    model_config = FROZEN

    id: str
    label: str


class ReportQuestion(BaseModel):
    model_config = FROZEN

    text: str
    options: list[QuestionOption] = Field(default_factory=list)
    input_id: str | None = None


class Usage(BaseModel):
    model_config = FROZEN

    llm_calls: int = 0
    sql_runs: int = 0
    elapsed_ms: int = 0


class AgentReport(BaseModel):
    model_config = FROZEN

    contract: Literal["AgentReport@1"] = "AgentReport@1"
    run_id: str | None = None
    step_id: str | None = None
    idempotency_key: str | None = None
    state: ReportState
    partial: bool = False
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    snapshot_id: str | None = None
    semantic_config_version: str | None = None
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    error: ReportError | None = None
    question: ReportQuestion | None = None
    data_confidence: str | None = None
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def _state_consistent(self) -> AgentReport:
        if self.state in ("failed", "rejected") and self.error is None:
            raise ValueError(f"state {self.state} needs an error")
        if self.state == "input_required" and self.question is None:
            raise ValueError("state input_required needs a question")
        if self.state == "completed" and self.error is not None:
            raise ValueError("a completed report carries no error")
        return self


@dataclass(frozen=True)
class ParseError:
    reason: str


_FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.S)


def render_agent_report(summary_vi: str, report: AgentReport) -> str:
    body = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return f"{summary_vi.strip()}\n\n```json\n{body}\n```"


def parse_agent_report(text: str) -> AgentReport | ParseError:
    fences = _FENCE.findall(text)
    if len(fences) != 1:
        return ParseError(f"expected exactly one ```json fence, found {len(fences)}")
    try:
        data = json.loads(fences[0])
    except json.JSONDecodeError as exc:
        return ParseError(f"invalid JSON: {exc.msg}")
    try:
        return AgentReport.model_validate(data)
    except ValidationError as exc:
        return ParseError(f"not an AgentReport@1: {exc.error_count()} error(s)")
