"""AgentCatalog: what each worker agent publishes so the Orchestrator can plan (build spec 00 §4.1, R-02)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import OutputKind, TaskKind

FROZEN = ConfigDict(extra="forbid", frozen=True)

WorkerAgent = Literal["data", "compare", "insight", "chart", "report"]


class CatalogOperation(BaseModel):
    model_config = FROZEN

    operation: str
    description: str = Field(max_length=200)
    input_schema: dict[str, Any] = Field(default_factory=dict)  # JSON Schema of the spec fields the planner may fill
    input_fields: dict[str, str] = Field(default_factory=dict)  # artifact kind → spec field receiving the ref
    requires: list[str] = Field(default_factory=list)  # → HARD waits
    uses_if_present: list[str] = Field(default_factory=list)  # → SOFT waits
    produces: list[str] = Field(default_factory=list)
    outputs: list[OutputKind] = Field(default_factory=list)
    serves: list[TaskKind] = Field(default_factory=list)
    deadline_s: int = Field(default=120, gt=0)  # R-08
    error_codes: dict[str, ErrorClass] = Field(default_factory=dict)
    retries_transient_internally: bool = False


class VocabEntry(BaseModel):
    model_config = FROZEN

    name: str
    description: str


class Vocabulary(BaseModel):
    model_config = FROZEN

    metrics: list[VocabEntry] = Field(default_factory=list)
    dimensions: list[VocabEntry] = Field(default_factory=list)
    filters: list[VocabEntry] = Field(default_factory=list)
    attributes: list[VocabEntry] = Field(default_factory=list)


class AgentCatalog(BaseModel):
    model_config = FROZEN

    agent: WorkerAgent
    contract_version: str
    catalog_version: str
    operations: list[CatalogOperation] = Field(min_length=1)
    vocabulary: Vocabulary = Field(default_factory=Vocabulary)
    fixture: bool = False  # True = stub for tests, not a contract (build spec 00 §4.3)

    def operation(self, name: str) -> CatalogOperation:
        for op in self.operations:
            if op.operation == name:
                return op
        raise KeyError(f"{self.agent} has no operation {name!r}")

    def classify(self, code: str, operation: str | None = None) -> ErrorClass:
        """Class of an error code; a code the catalog does not declare is FATAL (never retried)."""
        ops = [self.operation(operation)] if operation else self.operations
        for op in ops:
            if code in op.error_codes:
                return op.error_codes[code]
        return ErrorClass.FATAL
