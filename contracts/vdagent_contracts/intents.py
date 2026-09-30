"""Task kinds, requested outputs and agent groups (build spec 00 §2; R-02: task kinds replace PRD intents)."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vdagent_contracts.catalog import AgentCatalog, CatalogOperation


class TaskKind(StrEnum):
    LOOKUP = "LOOKUP"
    COMPARE = "COMPARE"
    TREND = "TREND"
    EXPLAIN = "EXPLAIN"


class OutputKind(StrEnum):
    CHAT_ANSWER = "CHAT_ANSWER"
    CHART = "CHART"
    REPORT = "REPORT"


class AgentGroup(StrEnum):
    CRITICAL_PATH = "CRITICAL_PATH"
    ANALYTICAL = "ANALYTICAL"
    OUTPUT = "OUTPUT"


AGENT_GROUP: dict[str, AgentGroup] = {
    "data": AgentGroup.CRITICAL_PATH,
    "compare": AgentGroup.ANALYTICAL,
    "insight": AgentGroup.ANALYTICAL,
    "chart": AgentGroup.ANALYTICAL,
    "report": AgentGroup.OUTPUT,
}


def operation_serves(agent: str, op: CatalogOperation) -> set[TaskKind]:
    """Task kinds an operation answers: its declared `serves`, else the temporary INT-8 table."""
    if op.serves:
        return set(op.serves)
    if agent == "data" and op.operation in ("aggregate_metrics", "fetch_units"):
        return {TaskKind.LOOKUP}
    if agent == "compare":
        return {TaskKind.COMPARE}
    return set()


def served_task_kinds(catalogs: Iterable[AgentCatalog]) -> set[TaskKind]:
    return {kind for catalog in catalogs for op in catalog.operations for kind in operation_serves(catalog.agent, op)}
