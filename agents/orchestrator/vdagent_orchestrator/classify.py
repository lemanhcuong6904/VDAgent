"""Error classification (build spec 01 §10.1): report → outcome, class → handling. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import AGENT_GROUP, AgentGroup
from vdagent_contracts.reports import AgentReport
from vdagent_orchestrator.catalogs import CatalogRegistry

TIER2_CLASSES = {ErrorClass.WRONG_RESULT, ErrorClass.SPEC_ISSUE, ErrorClass.NO_DATA}
ALERT_CLASSES = {ErrorClass.DATA_QUALITY, ErrorClass.QUOTA_EXHAUSTED, ErrorClass.TRANSIENT, ErrorClass.FATAL}


@dataclass(frozen=True)
class Outcome:
    kind: Literal["DONE", "ERROR", "QUESTION"]
    error_class: ErrorClass | None = None
    code: str | None = None
    warnings: tuple[str, ...] = ()
    partial: bool = False


@dataclass(frozen=True)
class Handling:
    action: Literal["ASK_SALES_OPS", "REPLAN", "DECISION", "REPORT_DIRECT", "CANCEL"]
    ops_alert: bool = False
    run_fails: bool = False


def classify(report: AgentReport, *, agent: str, operation: str, registry: CatalogRegistry,
             run_canceled: bool = False) -> Outcome:
    if run_canceled or report.state == "canceled":
        return Outcome("ERROR", ErrorClass.CANCELED, report.error.code if report.error else "CANCELED")
    if report.state == "completed":  # LOW_CONFIDENCE and the like stay warnings
        return Outcome("DONE", warnings=tuple(report.warnings), partial=report.partial)
    if report.state == "input_required":
        return Outcome("QUESTION", ErrorClass.NEED_INPUT)
    assert report.error is not None
    code = report.error.code
    if code == "BUDGET_EXCEEDED" and report.artifact_refs:  # Q-26 default: a partial package counts as done
        return Outcome("DONE", warnings=(*report.warnings, "BUDGET_EXCEEDED"), partial=True)
    try:
        cls = registry.catalogs[agent].classify(code, operation)
    except KeyError:  # agent or operation unknown to the catalogs
        cls = ErrorClass.FATAL
    return Outcome("ERROR", cls, code)


def handling(cls: ErrorClass, agent: str, *, tier2_available: bool) -> Handling:
    """§10.1 table. OUTPUT steps never go to tier 2/3; tier 2 is off in limited mode or without LLM planning."""
    if cls is ErrorClass.CANCELED:
        return Handling("CANCEL")
    if cls is ErrorClass.NEED_INPUT:
        return Handling("ASK_SALES_OPS")
    if cls in TIER2_CLASSES and AGENT_GROUP.get(agent) is not AgentGroup.OUTPUT:
        if tier2_available:
            return Handling("REPLAN")
        if cls is ErrorClass.WRONG_RESULT:
            return Handling("DECISION")
    return Handling("REPORT_DIRECT", ops_alert=cls in ALERT_CLASSES, run_fails=cls is ErrorClass.DATA_QUALITY)


__all__ = ["Handling", "Outcome", "classify", "handling"]
