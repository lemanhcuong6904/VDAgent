"""Wave dispatcher (D3): the Orchestrator sends every step whose waits are satisfied in one wave, reads the
AgentReports, and repeats. Agents never forward to each other; input packages travel in `StepSpec.input_refs`.

Waits (§6.3): a wait is satisfied when its step completed, or when it was released (SOFT, ended without a package).
Snapshot pin: the first Data step to finish sets the run snapshot; if it fails first, one waiting Data step is
released to become the new pin and the others are rewired to it. Errors are classified (§10.1) and propagated (§10.2);
questions, replans and decisions are left in `run.pending` for their handlers. The run closes once (FIN-1, V13).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.reports import AgentReport, ParseError, parse_agent_report
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.classify import ALERT_CLASSES, Outcome, classify, handling
from vdagent_orchestrator.close import summarize
from vdagent_orchestrator.planning import step_spec
from vdagent_orchestrator.propagate import StepView, propagate
from vdagent_orchestrator.records import RunRecord, StepRecord
from vdagent_orchestrator.wiring import WaitEntry

GRACE_S = 15
RETRY_RESERVE = 2  # extra steps allowed only for Sales Ops "retry" (§2)
AWAITING = {"awaiting_replan", "awaiting_decision"}
TIMEOUT_REPLY = "error: TIMEOUT"
NON_TERMINAL = {"pending", "working", "input_required"}


@dataclass(frozen=True)
class Outbound:
    step_id: str
    agent: str
    message: str  # StepSpec@1 JSON
    timeout_s: int


class Sender(Protocol):
    async def send(self, wave: Sequence[Outbound]) -> list[str]:
        """Send every item concurrently; one reply text per item, `TIMEOUT_REPLY` past `timeout_s`, `error: …` when
        delivery fails."""
        ...


def _satisfied(run: RunRecord, step: StepRecord, wait: WaitEntry) -> bool:
    target = run.steps.get(wait.step_id)
    return wait.step_id in step.released or (target is not None and target.status == "completed")


def ready(run: RunRecord) -> list[StepRecord]:
    return [s for s in run.ordered() if (s.status == "working" and s.resend)
            or (s.status == "pending" and all(_satisfied(run, s, w) for w in s.waits))]


def _outbound(run: RunRecord, step: StepRecord) -> Outbound:
    planned = run.plan.step(step.step_id)
    refs = [ref for w in step.waits if not w.snapshot_only and run.steps[w.step_id].status == "completed"
            for ref in run.steps[w.step_id].refs]
    released = [w.step_id for w in step.waits if not w.snapshot_only and w.step_id in step.released]
    spec = step_spec(planned, run.plan, user_context=run.user_context, question=run.frame.original_question,
                     snapshot_id=run.snapshot_id, semantic_config_version=run.semantic_config_version, input_refs=refs,
                     released_inputs=released, answered_choices=run.frame.answered_choices)
    return Outbound(step.step_id, step.agent, spec.model_dump_json(), planned.deadline_s + GRACE_S)


def _fail(run: RunRecord, step: StepRecord, code: str, cls: ErrorClass, message: str, *, alert: str | None = None) -> None:
    step.status, step.error_code, step.error_class, step.error_message = "failed", code, cls, message
    run.event("STEP_FAILED", step_id=step.step_id, code=code, error_class=cls.value)
    if alert:
        run.ops_alerts.append({"kind": alert, "run_id": run.run_id, "step_id": step.step_id, "code": code, "reason": message})


def report_direct(run: RunRecord, step: StepRecord) -> None:
    """Propagate a step that ended without a package (§10.2 "reported directly"), with the snapshot re-pin."""
    views = [StepView(s.step_id, s.status, tuple(s.waits)) for s in run.ordered()]
    actions = propagate(step.step_id, "DIRECT", views)
    repin = step.agent == "data" and run.snapshot_id is None
    new_pin: str | None = None
    for action in actions:
        target = run.steps[action.step_id]
        if action.kind == "SKIP_CANCEL":
            target.status = "skipped"
            run.event("STEP_SKIPPED", step_id=target.step_id, because=action.from_step)
            continue
        wait = next(w for w in target.waits if w.step_id == action.from_step)
        if repin and wait.snapshot_only and action.from_step == step.step_id:
            if new_pin is None:
                new_pin = target.step_id  # becomes the pin: runs now, sets the snapshot
            else:
                target.waits = [WaitEntry(step_id=new_pin, mode="SOFT", snapshot_only=True) if w is wait else w
                                for w in target.waits]
                run.event("STEP_REWIRED", step_id=target.step_id, to=new_pin)
                continue
        target.released.append(action.from_step)


def rewire(run: RunRecord, old: str, new: str) -> None:
    """REWIRE every unfinished waiter of `old` to `new` (replacement by tier 2 or a tier 3 retry)."""
    for waiter in run.steps.values():
        if waiter.status in NON_TERMINAL and any(w.step_id == old for w in waiter.waits):
            waiter.waits = [WaitEntry(step_id=new, mode=w.mode, artifact_kinds=w.artifact_kinds, snapshot_only=w.snapshot_only)
                            if w.step_id == old else w for w in waiter.waits]
            run.event("STEP_REWIRED", step_id=waiter.step_id, old=old, new=new)


def tier3_eligible(run: RunRecord) -> bool:
    """§10.3: one decision question per run, and a retry must still be possible."""
    return not run.decision_asked and run.retry_reserve_used < RETRY_RESERVE


def escalate(run: RunRecord, step: StepRecord) -> None:
    """After tier 2 (used or unavailable): WRONG_RESULT → tier 3 decision when eligible; else reported directly."""
    step.flags = [f for f in step.flags if f not in AWAITING]
    if step.error_class is ErrorClass.WRONG_RESULT and tier3_eligible(run):
        step.flags.append("awaiting_decision")
        run.pending.append({"kind": "DECISION", "step_id": step.step_id})
    else:
        report_direct(run, step)


def _handle_error(run: RunRecord, step: StepRecord, outcome: Outcome, message: str, tier2: bool) -> None:
    assert outcome.error_class is not None and outcome.code is not None
    cls = outcome.error_class
    todo = handling(cls, step.agent, tier2_available=tier2 and run.plan.may_replan and not step.replan_used)
    if todo.action == "CANCEL":
        step.status = "canceled"
        run.event("STEP_CANCELED", step_id=step.step_id)
        report_direct(run, step)
        return
    _fail(run, step, outcome.code, cls, message, alert=cls.value if todo.ops_alert else None)
    if todo.run_fails:
        run.event("RUN_MUST_FAIL", step_id=step.step_id, code=outcome.code)
    if todo.action == "REPLAN":
        step.flags.append("awaiting_replan")
        run.pending.append({"kind": "REPLAN", "step_id": step.step_id})
    elif todo.action == "DECISION":
        escalate(run, step)
    else:
        report_direct(run, step)


def _accept(run: RunRecord, step: StepRecord, reply: str, registry: CatalogRegistry, tier2: bool) -> None:
    if reply == TIMEOUT_REPLY:
        _fail(run, step, "TIMEOUT", ErrorClass.FATAL, "Bước xử lý quá thời gian cho phép.", alert="TIMEOUT")
        report_direct(run, step)
        return
    if reply.startswith("error:"):
        _fail(run, step, "DELIVERY_FAILED", ErrorClass.FATAL, reply, alert="DELIVERY_FAILED")
        report_direct(run, step)
        return
    parsed = parse_agent_report(reply)
    planned = run.plan.step(step.step_id)
    if isinstance(parsed, ParseError) or not _matches(parsed, run, planned.idempotency_key, step.step_id):
        reason = parsed.reason if isinstance(parsed, ParseError) else "báo cáo không khớp run/bước"
        _fail(run, step, "REPORT_UNPARSEABLE", ErrorClass.FATAL, reason, alert="FATAL")
        report_direct(run, step)
        return
    outcome = classify(parsed, agent=step.agent, operation=step.operation, registry=registry)
    if outcome.kind == "DONE":
        step.status, step.refs, step.summary = "completed", list(parsed.artifact_refs), parsed.summary
        step.partial, step.warnings, step.data_confidence = outcome.partial, list(outcome.warnings), parsed.data_confidence
        run.warnings += [{"step_id": step.step_id, "code": w} for w in outcome.warnings]
        if step.agent == "data" and run.snapshot_id is None and parsed.snapshot_id:
            run.snapshot_id, run.semantic_config_version = parsed.snapshot_id, parsed.semantic_config_version
            run.event("SNAPSHOT_PINNED", step_id=step.step_id, snapshot_id=parsed.snapshot_id)
        run.event("STEP_COMPLETED", step_id=step.step_id)
    elif outcome.kind == "QUESTION":
        step.status, step.question = "input_required", parsed.question
        run.pending.append({"kind": "INPUT", "step_id": step.step_id})
        run.event("INPUT_REQUESTED", step_id=step.step_id)
    else:
        _handle_error(run, step, outcome, parsed.error.message if parsed.error else "", tier2)


def _matches(report: AgentReport, run: RunRecord, key: str, step_id: str) -> bool:
    return ((report.run_id in (None, run.run_id)) and (report.step_id in (None, step_id))
            and (report.idempotency_key in (None, key)))


def maybe_close(run: RunRecord) -> bool:
    """FIN-1: every step terminal, none flagged, nothing pending → close, exactly once."""
    if run.finished or run.pending:
        return False
    if any(s.status in NON_TERMINAL or (s.status == "failed" and set(s.flags) - {"dropped"}) for s in run.steps.values()):
        return False
    summary = summarize(run)
    run.status, run.finished, run.summary = summary.status, True, summary.model_dump(mode="json")
    run.event("RUN_FINISHED", status=run.status, reason=summary.reason)
    return True


async def drive(run: RunRecord, *, sender: Sender, registry: CatalogRegistry, tier2_available: bool,
                max_waves: int | None = None) -> RunRecord:
    """Send waves until nothing is ready, or `max_waves` waves were sent (the turn's step budget, R7)."""
    if run.finished:
        return run
    sent = 0
    while (max_waves is None or sent < max_waves) and (wave := ready(run)):
        sent += 1
        for step in wave:
            step.status, step.resend = "working", False
            run.event("STEP_OPENED", step_id=step.step_id)
        outbound = [_outbound(run, s) for s in wave]
        replies = await sender.send(outbound)
        for step, reply in zip(wave, replies, strict=True):
            _accept(run, step, reply, registry, tier2_available)
    maybe_close(run)
    return run


__all__ = ["ALERT_CLASSES", "GRACE_S", "RETRY_RESERVE", "TIMEOUT_REPLY", "Outbound", "Sender", "drive",
           "escalate", "maybe_close", "ready", "report_direct", "rewire", "tier3_eligible"]
