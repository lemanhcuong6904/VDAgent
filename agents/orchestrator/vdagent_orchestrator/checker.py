"""Plan checker (build spec 01 §7): 12 deterministic rules, pure `check(plan, frame, registry, state) → [Violation]`.

CHK-RECHECK is out of scope (DEC-026): plans are applied in the same turn they are checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from vdagent_contracts.catalog import CatalogOperation
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import OutputKind, TaskKind, operation_serves
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.intent import IntentFrame
from vdagent_orchestrator.planning import STEP_ID, Plan

UNUSABLE = {"failed", "skipped", "canceled"}
REPLACEABLE = {ErrorClass.WRONG_RESULT, ErrorClass.SPEC_ISSUE, ErrorClass.NO_DATA}
VOCAB_FIELDS = {"metrics": "metrics", "group_by": "dimensions", "dimensions": "dimensions", "filters": "filters",
                "attributes": "attributes"}


@dataclass(frozen=True)
class ExistingStep:
    """A step already in the run (earlier plans)."""

    step_id: str
    agent: str
    operation: str
    status: str  # pending | working | input_required | completed | failed | skipped | canceled
    error_class: ErrorClass | None = None
    owner_replan: str | None = None  # REPLAN task that owns this failed step
    replan_used: bool = False  # its part already used the LLM replacement (§11)
    awaiting: bool = False  # failed but awaiting replan / decision: still counts as an input
    dropped: bool = False


@dataclass(frozen=True)
class RunState:
    steps: tuple[ExistingStep, ...] = ()
    reused_kinds: frozenset[str] = frozenset()  # kinds provided by reused parent-run packages
    step_count: int = 0  # every step of the run so far, incl. failed / dropped / replaced
    max_steps: int = 10
    retry_reserve: int = 0  # extra steps allowed only for Sales Ops "retry"
    replan_id: str | None = None  # the REPLAN task this plan comes from
    will_exist_outputs: frozenset[OutputKind] = frozenset()  # owned by later queued REPLAN tasks
    will_exist_kinds: frozenset[TaskKind] = frozenset()


@dataclass(frozen=True)
class Violation:
    code: str
    step_id: str | None
    detail: str

    def __str__(self) -> str:
        return f"{self.code} {self.step_id or '-'}: {self.detail}"


def _op(registry: CatalogRegistry, agent: str, operation: str) -> CatalogOperation | None:
    try:
        return registry.operation(agent, operation)
    except KeyError:
        return None


def _usable(step: ExistingStep, dropped: set[str]) -> bool:
    if step.dropped or step.step_id in dropped:
        return False
    return step.status not in UNUSABLE or (step.status == "failed" and step.awaiting)


def _spec_problems(spec: dict[str, Any], op: CatalogOperation, vocab: dict[str, list[str]]) -> list[str]:
    problems = [e.message for e in Draft202012Validator(op.input_schema).iter_errors(spec)] if op.input_schema else []
    for key, kind in VOCAB_FIELDS.items():
        values = spec.get(key)
        if isinstance(values, list):
            problems += [f"{key}: '{v}' không có trong danh mục Data" for v in values if v not in vocab[kind]]
    return problems


def _has_cycle(graph: dict[str, list[str]]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        stack.pop()
        state[node] = 2
        return []

    for node in graph:
        if node not in state and (found := visit(node)):
            return found
    return []


def check(plan: Plan, frame: IntentFrame, registry: CatalogRegistry, state: RunState) -> list[Violation]:
    out: list[Violation] = []

    def add(code: str, step_id: str | None, detail: str) -> None:
        out.append(Violation(code, step_id, detail))

    existing = {s.step_id: s for s in state.steps}
    dropped = set(plan.drop)
    ops = {s.step_id: _op(registry, s.agent, s.operation) for s in plan.steps}
    produces: dict[str, set[str]] = {sid: set(op.produces) if op else set() for sid, op in ops.items()}
    for e in state.steps:
        if e.step_id not in produces:
            op = _op(registry, e.agent, e.operation)
            produces[e.step_id] = set(op.produces) if op else set()
    usable_existing = [e for e in state.steps if _usable(e, dropped)]
    vocab = registry.vocabulary()
    seen: set[str] = set()

    for step in plan.steps:
        sid, op = step.step_id, ops[step.step_id]
        if not re.fullmatch(STEP_ID, sid) or sid in existing or sid in seen:  # BAD_STEP_ID
            add("BAD_STEP_ID", sid, "mã bước sai dạng hoặc đã dùng trong run")
        seen.add(sid)
        if op is None:  # UNKNOWN_OPERATION
            add("UNKNOWN_OPERATION", sid, f"{step.agent}.{step.operation} không có trong danh mục")
            continue
        for problem in _spec_problems(step.spec, op, vocab):  # SPEC_INVALID
            add("SPEC_INVALID", sid, problem)
        receives = set(op.requires) | set(op.uses_if_present)
        good_inputs: list[str] = []
        for i in step.inputs:  # BAD_WIRING
            if i in ops:
                ok = i not in dropped
            elif i in existing:
                ok = _usable(existing[i], dropped)
            else:
                add("BAD_WIRING", sid, f"bước đầu vào {i} không tồn tại")
                continue
            if not ok:
                add("BAD_WIRING", sid, f"bước đầu vào {i} không dùng được")
            elif not produces[i] & receives:
                add("BAD_WIRING", sid, f"bước đầu vào {i} không tạo thứ bước này cần hoặc dùng")
            else:
                good_inputs.append(i)
        available = set().union(*(produces[i] for i in good_inputs)) | set(state.reused_kinds)
        for kind in op.requires:  # MISSING_REQUIRED_INPUT
            if kind not in available:
                add("MISSING_REQUIRED_INPUT", sid, f"thiếu đầu vào loại {kind}")
        scope = step.spec.get("scope")
        mentions = scope.get("mentions", []) if isinstance(scope, dict) else []
        allowed = {m.text for m in frame.mentions}
        for m in mentions:  # MENTION_NOT_IN_REQUEST
            text = m.get("text") if isinstance(m, dict) else None
            if text not in allowed:
                add("MENTION_NOT_IN_REQUEST", sid, f"đối tượng '{text}' không có trong câu hỏi")
        if step.replaces is not None:  # BAD_REPLACEMENT
            old = existing.get(step.replaces)
            owned_failure = (old is not None and old.status == "failed" and state.replan_id is not None
                             and old.owner_replan == state.replan_id and old.error_class in REPLACEABLE and not old.replan_used)
            dropped_pending = old is not None and old.status == "pending" and step.replaces in dropped
            if not (owned_failure or dropped_pending):
                add("BAD_REPLACEMENT", sid, f"không được thay bước {step.replaces}")
            elif not produces[step.replaces] <= set(op.produces):
                add("BAD_REPLACEMENT", sid, f"bước thay không tạo đủ thứ bước {step.replaces} tạo")

    cycle = _has_cycle({s.step_id: list(s.inputs) for s in plan.steps})  # CYCLE
    if cycle:
        add("CYCLE", cycle[0], " → ".join(cycle))

    live_ops = [(s.agent, op) for s in plan.steps if (op := ops[s.step_id]) is not None]
    live_ops += [(e.agent, op) for e in usable_existing if (op := _op(registry, e.agent, e.operation)) is not None]
    covered = {o for _, op in live_ops for o in op.outputs} | set(state.will_exist_outputs)
    for output in frame.requested_outputs:  # OUTPUT_NOT_COVERED
        if output not in covered:
            add("OUTPUT_NOT_COVERED", None, f"không bước nào tạo output {output.value}")
    has_data = any(agent == "data" for agent, _ in live_ops) or bool(state.reused_kinds)
    if not has_data:  # TASK_MIN_STEPS
        add("TASK_MIN_STEPS", None, "kế hoạch cần ít nhất một bước Data")
    served = {k for agent, op in live_ops for k in operation_serves(agent, op)} | set(state.will_exist_kinds)
    for kind in frame.task_kinds:
        if kind not in frame.uncovered_task_kinds and kind not in served:
            add("TASK_MIN_STEPS", None, f"không bước nào phục vụ loại câu hỏi {kind.value}")

    for d in plan.drop:  # BAD_DROP
        old = existing.get(d)
        owned_failure = (old is not None and old.status == "failed" and state.replan_id is not None
                         and old.owner_replan == state.replan_id)
        if not (old is not None and (old.status == "pending" or owned_failure)):
            add("BAD_DROP", d, "chỉ được bỏ bước chưa chạy hoặc bước lỗi do lần lập lại này sở hữu")

    if state.step_count + len(plan.steps) > state.max_steps + state.retry_reserve:  # PLAN_LIMIT_EXCEEDED
        add("PLAN_LIMIT_EXCEEDED", None, f"tổng số bước vượt {state.max_steps}")
    return out


__all__ = ["ExistingStep", "RunState", "Violation", "check"]
