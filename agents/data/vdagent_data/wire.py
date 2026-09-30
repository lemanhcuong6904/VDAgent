"""The door of the Data agent for the Orchestrator contract v1.0 (contract_agent.md, tab Data).

`Door.handle(text, tools)` takes one message and gives back one reply, both JSON objects of the contract:

    DISPATCH      → REPORT  DONE | ERROR | QUESTION          (this build runs the step at once, so the COMMAND_ACK that the
                                                               contract puts before the REPORT is implied by it)
    ANSWER        → REPORT  (the step runs again with the user's choice kept in the run's pins)
    START, CANCEL → COMMAND_ACK ACCEPTED, or REJECTED UNKNOWN_STEP for a step never dispatched here
    STATUS_QUERY  → STATUS  with the last REPORT of the step
    REWIRE, RELEASE, FORWARD, REPORT → COMMAND_ACK REJECTED UNKNOWN_MESSAGE_TYPE (the asynchronous protocol is not in this build)
    a message that is not valid       → COMMAND_ACK REJECTED with MALFORMED_MESSAGE, UNSUPPORTED_CONTRACT_VERSION,
                                        UNKNOWN_MESSAGE_TYPE or WRONG_AGENT, before anything is read

The same idempotency key with the same content gets the stored answer and reads nothing; with another content it is
ID_CONFLICT; `retry_kind = USER_RETRY` runs again. The registry lives in the process (it is lost on restart: a re-sent step
simply runs again, which is safe because every write is a new immutable version).

Nothing here touches the warehouse: `vdagent_data.v1` does, and every reply is validated by the contract's own models
(`vdagent_data.contract_v1`) before it leaves, so a reply that breaks the contract is a bug that the tests catch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, get_args

from pydantic import ValidationError

from vdagent_contracts.canonical import canonical_json
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import ReportError
from vdagent_contracts.scope import AuthorizedScope, UserContext
from vdagent_data import contract_v1 as c
from vdagent_data import steps as core
from vdagent_data.resolve import name_form
from vdagent_data.trace import Observer
from vdagent_data.v1 import ERROR_TABLE, V1Result, run_step_v1

_FROM_PREFIX = re.compile(r"^\[from: [^\]]+\]\s*")
MAX_OPTIONS = 10
PACKAGE_OF_OPERATION = {"fetch_units": ("dataset", "unit_set"), "aggregate_metrics": ("metric", "metric_table")}
# the class of every code of table D (contract_agent.md, tab Data): what the Orchestrator does with the step
TABLE_D_CLASS = {
    "SPEC_MISMATCH": "SPEC_ISSUE", "SPEC_INVALID": "SPEC_ISSUE", "DATA_UNAVAILABLE": "NO_DATA", "EMPTY_RESULT": "NO_DATA",
    "OUT_OF_SCOPE": "NO_ACCESS", "DQ_BLOCKING": "DATA_QUALITY", "RESULT_TRUNCATED": "SPEC_ISSUE", "BUDGET_EXCEEDED": "SPEC_ISSUE",
    "CONFIG_MISSING": "FATAL", "ID_CONFLICT": "FATAL", "LLM_UNAVAILABLE": "TRANSIENT", "LLM_QUOTA": "QUOTA_EXHAUSTED",
    "WORKER_LOST": "TRANSIENT", "CANCELED": "CANCELED",
}
_STATE_OF_CODE = {"SPEC_INVALID": "rejected", "OUT_OF_SCOPE": "rejected", "ID_CONFLICT": "rejected", "CANCELED": "canceled"}  # the rest: failed


# ---- is it ours? -------------------------------------------------------------------------------------------------------------


def _json_object(text: str) -> dict[str, Any] | None:
    body = _FROM_PREFIX.sub("", text, count=1).strip()
    if not body.startswith("{"):
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_v1(text: str) -> bool:
    """A JSON object that says `contract_version` and `message_type` is a message of contract v1.0 (right or wrong)."""
    data = _json_object(text)
    return data is not None and isinstance(data.get("contract_version"), str) and isinstance(data.get("message_type"), str)


# ---- warnings and confidence -------------------------------------------------------------------------------------------------

_LIMITATION_TEXT = {
    "METRIC_UNAVAILABLE": "Kho dữ liệu không có chỉ số {0}; để trống, không điền 0.",
    "WINDOW_INCOMPLETE": "Bảng phễu chỉ phủ {1}/30 ngày nên không cộng số lead {0}; để trống, không điền thiếu.",
    "DQ_MISSING": "{1} dòng thiếu giá trị {0}.",
    "PEER_AREA_UNAVAILABLE": "{0} căn thiếu diện tích ròng nên bị loại khỏi ứng viên.",
    "SYNTHETIC_SOURCE": "Trường {0} là dữ liệu mô phỏng.",
    "BLOCKED": "{0} đang chờ quyết định nghiệp vụ nên chưa áp dụng.",
}
_TARGET_FIRST = {"METRIC_UNAVAILABLE", "WINDOW_INCOMPLETE", "DQ_MISSING", "SYNTHETIC_SOURCE"}


def map_warning(raw: str) -> dict[str, Any]:
    """An internal warning string → `{code, message, target?, details}` with one of the contract's eight codes (§E)."""
    head, *rest = raw.split(":")
    target = rest[0] if rest else None
    details = {"raw": raw}
    if head == "PROVISIONAL_DEFINITION":
        return {"code": head, "message": f"Chỉ số {target} dùng định nghĩa tạm thời, chưa được team DATA duyệt.", "target": target, "details": details}
    if head == "CONFIG_PENDING":
        return {"code": "PROVISIONAL_DEFINITION", "message": f"Ngưỡng {target} chưa được duyệt; kết quả dùng ngưỡng này là tạm thời.",
                "target": target, "details": details}
    if head == "EMPTY_RESULT":
        return {"code": head, "message": "Không có dòng nào khớp; bước cho phép kết quả rỗng.", "details": details}
    if head == "SMALL_SAMPLE":
        return {"code": head, "message": "Mẫu nhỏ hơn số tối thiểu đã duyệt.", "details": details}
    if head == "SNAPSHOT_STATUS_ASSUMED":
        return {"code": "LIMITATION", "message": "Kho không có cột trạng thái duyệt của kỳ chốt; coi là đã duyệt, chờ team DATA xác nhận.",
                "target": "snapshot", "details": details}
    if head == "OUT_OF_CATALOG_NEED_NOT_SERVED":
        return {"code": "LIMITATION", "message": "Nhu cầu ngoài catalog chưa được phục vụ (bản này chưa có T3); phần trong catalog đã làm.",
                "target": "out_of_catalog_need", "details": details}
    text = _LIMITATION_TEXT.get(head)
    message = text.format(*(rest + ["?", "?"])) if text else raw
    return {"code": "LIMITATION", "message": message[:300], "target": target if head in _TARGET_FIRST else None, "details": details}


@dataclass(frozen=True)
class Confidence:
    level: str
    reasons: list[str]


_MISSING = ("METRIC_UNAVAILABLE", "DQ_MISSING", "WINDOW_INCOMPLETE", "PEER_AREA_UNAVAILABLE")
_TENTATIVE = ("PROVISIONAL_DEFINITION", "CONFIG_PENDING", "SMALL_SAMPLE", "SYNTHETIC_SOURCE", "SNAPSHOT_STATUS_ASSUMED", "BLOCKED",
              "OUT_OF_CATALOG_NEED_NOT_SERVED", "EMPTY_RESULT")


def confidence(warnings: list[str]) -> Confidence:
    """HIGH: every number comes from approved rules and complete data. MEDIUM: something is provisional or assumed. LOW: data is missing."""
    heads = [w.split(":")[0] for w in warnings]
    missing = sorted({w.split(":")[1] for w in warnings if w.split(":")[0] in _MISSING and ":" in w})
    if any(h in _MISSING for h in heads):
        reasons = [("Thiếu dữ liệu: " + ", ".join(missing))[:200]] if missing else ["Thiếu dữ liệu ở một số trường"]
        tentative = sorted({h for h in heads if h in _TENTATIVE})
        if tentative:
            reasons.append(("Có điểm tạm thời: " + ", ".join(tentative))[:200])
        return Confidence("LOW", reasons)
    tentative = sorted({h for h in heads if h in _TENTATIVE})
    if tentative:
        return Confidence("MEDIUM", [("Có điểm tạm thời hoặc giả định: " + ", ".join(tentative))[:200]])
    return Confidence("HIGH", ["Truy vấn tất định (T1), chỉ số đã duyệt, dữ liệu đầy đủ"])


# ---- replies -----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    message: dict[str, Any]
    text: str  # one line for people (the chat), never the contract's business

    def json(self) -> str:
        return json.dumps(self.message, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _dump(model: Any) -> dict[str, Any]:
    return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))


def _ack(in_reply_to: str, status: str, agent_ref: str | None = None, reject: tuple[str, str] | None = None) -> Reply:
    ack = c.CommandAck(in_reply_to=in_reply_to, ack_status=status, agent_ref=agent_ref,  # type: ignore[arg-type]
                       reject=c.Reject(code=reject[0], message=reject[1][:300]) if reject else None)  # type: ignore[arg-type]
    text = f"COMMAND_ACK {status}" + (f": {reject[1]}" if reject else "")
    return Reply(_dump(ack), text)


def _first_problem(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(p) for p in err["loc"] if not str(p).startswith(("function-after", "DISPATCH", "START")))
    return f"{where or 'message'}: {err['msg']}"[:300]


@dataclass
class Entry:
    fingerprint: str
    message: c.DispatchMessage
    agent_ref: str
    report: dict[str, Any] | None = None
    agent_state: str = "submitted"
    pending: dict[str, Any] | None = None  # {"question_id", "mention", "options": {option_id: entity_id}}
    canceled: bool = False
    seen: set[str] = field(default_factory=set)


class Door:
    def __init__(self, *, profile: str = "mock") -> None:
        self._profile = profile
        self._entries: dict[str, Entry] = {}  # by idempotency key
        self._by_step: dict[tuple[str, str], str] = {}
        self._pins: dict[str, dict[str, str]] = {}  # run_id → {normalized mention: entity id}

    async def handle(self, text: str, tools: core.Tools, observer: Observer | None = None) -> Reply:
        raw = _json_object(text) or {}
        message_id = raw.get("message_id")
        in_reply_to = message_id if isinstance(message_id, str) and 0 < len(message_id) <= 64 else "unknown"
        version = raw.get("contract_version")
        if not isinstance(version, str) or not c.supports(version):
            return _ack(in_reply_to, "REJECTED", reject=("UNSUPPORTED_CONTRACT_VERSION", f"this agent speaks contract {c.CONTRACT_VERSION.split('.')[0]}.x, not {version!r}"))
        if raw.get("message_type") not in get_args(c.MessageType):
            return _ack(in_reply_to, "REJECTED", reject=("UNKNOWN_MESSAGE_TYPE", f"unknown message_type {raw.get('message_type')!r}"))
        try:
            msg = c.parse_message(raw)
        except ValidationError as exc:
            return _ack(in_reply_to, "REJECTED", reject=("MALFORMED_MESSAGE", _first_problem(exc)))
        if msg.agent != "DATA":
            return _ack(msg.message_id, "REJECTED", reject=("WRONG_AGENT", f"this is the DATA agent, not {msg.agent}"))
        if isinstance(msg, c.DispatchMessage):
            return await self._dispatch(msg, tools, observer)
        if isinstance(msg, c.AnswerMessage):
            return await self._answer(msg, tools, observer)
        if isinstance(msg, (c.StartMessage, c.CancelMessage)):
            return self._control(msg)
        if isinstance(msg, c.StatusQueryMessage):
            return self._status(msg)
        return _ack(msg.message_id, "REJECTED", reject=("UNKNOWN_MESSAGE_TYPE", f"{msg.message_type} belongs to the asynchronous protocol, not in this build"))

    # ---- DISPATCH ------------------------------------------------------------------------------------------------------------

    async def _dispatch(self, msg: c.DispatchMessage, tools: core.Tools, observer: Observer | None) -> Reply:
        body = msg.body
        fingerprint = _fingerprint(body)
        entry = self._entries.get(msg.idempotency_key)
        if entry is not None and body.retry_kind != "USER_RETRY":
            if entry.fingerprint != fingerprint:
                return self._error(msg, "ID_CONFLICT", f"the key {msg.idempotency_key} was used with another content", None)
            entry.seen.add(msg.message_id)
            return self._replay(msg, entry)
        if any(w.dependency == "HARD" and w.purpose == "INPUT" for w in body.wait_list):
            return self._error(msg, "SPEC_INVALID", "the step waits for an input package; this build has no START/FORWARD protocol to receive it", None)
        if body.catalog_version.split(".")[0] != "1":
            return self._error(msg, "SPEC_INVALID", f"catalog version {body.catalog_version} is not supported (1.x is)", None)
        entry = Entry(fingerprint, msg, agent_ref=f"data:{msg.run_id}:{msg.step_id}")
        self._entries[msg.idempotency_key] = entry
        self._by_step[(msg.run_id, msg.step_id)] = msg.idempotency_key
        entry.seen.add(msg.message_id)
        return await self._run(msg, entry, tools, observer)

    async def _run(self, msg: c.DispatchMessage, entry: Entry, tools: core.Tools, observer: Observer | None) -> Reply:
        started = time.monotonic()
        step = _step_spec(msg)
        try:
            async with asyncio.timeout(msg.body.deadline_s):
                result = await run_step_v1(step, tools, observer, profile=self._profile, saved=self._pins.get(msg.run_id, {}))
        except TimeoutError:
            return self._error(msg, "BUDGET_EXCEEDED", f"the step did not finish in {msg.body.deadline_s} s", entry)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return self._report(msg, entry, result, elapsed_ms)

    def _replay(self, msg: c.DispatchMessage, entry: Entry) -> Reply:
        assert entry.report is not None
        message = {**entry.report, "message_id": _message_id("rpt"), "sent_at": _now()}
        return Reply(message, _line(message))

    # ---- the REPORT ----------------------------------------------------------------------------------------------------------

    def _header(self, msg: c.Header, prefix: str = "rpt") -> dict[str, Any]:
        head = {"contract_version": c.CONTRACT_VERSION, "message_id": _message_id(prefix), "sent_at": _now(), "message_type": "REPORT",
                "run_id": msg.run_id, "plan_id": msg.plan_id, "step_id": msg.step_id, "agent": "DATA", "idempotency_key": msg.idempotency_key}
        if msg.trace is not None:
            head["trace"] = _dump(msg.trace)
        return head

    def _store(self, entry: Entry | None, message: dict[str, Any], state: str, pending: dict[str, Any] | None = None) -> Reply:
        if entry is not None:
            entry.report, entry.agent_state, entry.pending = message, state, pending
        return Reply(message, _line(message))

    def _error(self, msg: c.DispatchMessage, code: str, reason: str, entry: Entry | None, details: dict[str, Any] | None = None) -> Reply:
        body = {"kind": "ERROR", "agent_state": _STATE_OF_CODE.get(code, "failed"), "agent_ref": f"data:{msg.run_id}:{msg.step_id}",
                "error": {"code": code, "class": TABLE_D_CLASS.get(code, "FATAL"), "reason": reason[:1000], **({"details": details} if details else {})}}
        message = _dump(c.ReportMessage.model_validate({**self._header(msg), "body": body}))
        return self._store(entry, message, body["agent_state"])

    def _report(self, msg: c.DispatchMessage, entry: Entry, result: V1Result, elapsed_ms: int) -> Reply:
        report = result.report
        usage = {"llm_calls": 0, "elapsed_ms": elapsed_ms}
        if report.state == "input_required" and result.question is not None:
            q = result.question
            options = q.options[:MAX_OPTIONS]
            question_id = "q-" + hashlib.sha1(f"{msg.run_id}|{msg.step_id}|{q.mention}".encode()).hexdigest()[:12]
            body = {"kind": "QUESTION", "agent_state": "input_required", "agent_ref": entry.agent_ref, "usage": usage,
                    "question": {"question_id": question_id, "reason_code": q.reason_code, "text": q.text[:500], "max_selections": 1, "subject_text": q.mention[:200],
                                 "options": [{"option_id": f"opt-{i}", "label": o.label[:200],
                                              "value": {"entity_id": o.id, "entity_kind": o.kind, "display_name": o.name[:200]}}
                                             for i, o in enumerate(options, 1)]}}
            message = _dump(c.ReportMessage.model_validate({**self._header(msg), "body": body}))
            pending = {"question_id": question_id, "mention": q.mention, "options": {f"opt-{i}": o.id for i, o in enumerate(options, 1)}}
            return self._store(entry, message, "input_required", pending)
        if report.state == "completed":
            return self._done(msg, entry, result, usage)
        error = report.error or ReportError(code="INTERNAL_ERROR", message=report.summary or "unknown failure")
        code, _ = ERROR_TABLE.get(error.code, ("INTERNAL_ERROR", core.ErrorClass.FATAL))
        details = {"internal_code": error.code} if error.code != code else None
        return self._error(msg, code, error.message, entry, details)

    def _done(self, msg: c.DispatchMessage, entry: Entry, result: V1Result, usage: dict[str, int]) -> Reply:
        report = result.report
        main_type, kind = PACKAGE_OF_OPERATION[result.operation]
        refs = {r.artifact_type.value: r for r in report.artifact_refs}
        main = refs[main_type]
        warnings = [map_warning(w) for w in report.warnings]
        level = confidence(report.warnings)
        body = {
            "kind": "DONE", "agent_state": "completed", "agent_ref": entry.agent_ref, "usage": usage,
            "result": {"package": {"package_id": f"{main.artifact_id}@{main.version}", "kind": kind, "status": "PARTIAL" if report.partial else "VALID",
                                   "content_hash": main.content_hash},
                       "snapshot_id": report.snapshot_id, "summary": report.summary[:800], "warnings": warnings},
            "ext": {"data_confidence": {"level": level.level, "reasons": level.reasons},
                    "related_packages": [{"kind": t, "package_id": f"{r.artifact_id}@{r.version}", "content_hash": r.content_hash}
                                         for t, r in refs.items() if t != main_type],
                    "semantic_config_version": report.semantic_config_version, "entities_resolved": result.resolved},
        }
        message = _dump(c.ReportMessage.model_validate({**self._header(msg), "body": body}))
        return self._store(entry, message, "completed")

    # ---- the other messages --------------------------------------------------------------------------------------------------

    async def _answer(self, msg: c.AnswerMessage, tools: core.Tools, observer: Observer | None) -> Reply:
        key = self._by_step.get((msg.run_id, msg.step_id))
        entry = self._entries.get(key) if key else None
        pending = entry.pending if entry else None
        if entry is None or pending is None or pending["question_id"] != msg.body.question_id:
            return _ack(msg.message_id, "REJECTED", reject=("UNKNOWN_STEP", f"no open question {msg.body.question_id} for step {msg.step_id}"))
        chosen = msg.body.selected_option_ids
        if len(chosen) != 1 or chosen[0] not in pending["options"]:
            return _ack(msg.message_id, "REJECTED", reject=("MALFORMED_MESSAGE", "the selected option is not one of the offered options"))
        self._pins.setdefault(msg.run_id, {})[name_form(pending["mention"])] = pending["options"][chosen[0]]
        entry.pending = None
        return await self._run(entry.message, entry, tools, observer)

    def _control(self, msg: c.StartMessage | c.CancelMessage) -> Reply:
        key = self._by_step.get((msg.run_id, msg.step_id))
        entry = self._entries.get(key) if key else None
        if entry is None:
            return _ack(msg.message_id, "REJECTED", reject=("UNKNOWN_STEP", f"step {msg.step_id} of run {msg.run_id} was never dispatched to this agent"))
        if isinstance(msg, c.CancelMessage):
            targets = [e for k, e in self._entries.items() if e.message.run_id == msg.run_id] if msg.body.scope == "RUN" else [entry]
            for e in targets:
                e.canceled, e.agent_state, e.pending = True, "canceled", None
        return _ack(msg.message_id, "ACCEPTED", agent_ref=entry.agent_ref)

    def _status(self, msg: c.StatusQueryMessage) -> Reply:
        entry = next((e for e in self._entries.values() if e.agent_ref == msg.body.agent_ref), None)
        if entry is None:
            return _ack(msg.message_id, "REJECTED", reject=("UNKNOWN_STEP", f"no step has the agent_ref {msg.body.agent_ref}"))
        last = c.ReportBody.model_validate(entry.report["body"]) if entry.report else None
        status = c.Status(in_reply_to=msg.message_id, agent_state=entry.agent_state, last_report=last)
        return Reply(_dump(status), f"STATUS {entry.agent_state}")


# ---- helpers -----------------------------------------------------------------------------------------------------------------


def _fingerprint(body: c.DispatchBody) -> str:
    content = {"operation": body.operation, "spec": body.spec, "user": body.user_context.user_id, "snapshot_id": body.snapshot_id,
               "question": body.original_question, "catalog_version": body.catalog_version}
    return hashlib.sha256(canonical_json(content).encode()).hexdigest()


def _step_spec(msg: c.DispatchMessage) -> StepSpec:
    b = msg.body
    return StepSpec(
        run_id=msg.run_id, plan_id=msg.plan_id, step_id=msg.step_id, idempotency_key=msg.idempotency_key, operation=b.operation, spec=b.spec,
        user_context=UserContext(user_id=b.user_context.user_id, role=b.user_context.role,
                                 authorized_scope=AuthorizedScope(**b.user_context.authorized_scope.model_dump())),
        snapshot_id=b.snapshot_id, semantic_config_version=None, original_question=b.original_question, deadline_s=b.deadline_s)


def _line(message: dict[str, Any]) -> str:
    body = message.get("body", {})
    if body.get("kind") == "DONE":
        return body["result"]["summary"]
    if body.get("kind") == "ERROR":
        return f"{body['error']['code']}: {body['error']['reason']}"
    if body.get("kind") == "QUESTION":
        return body["question"]["text"]
    return "REPORT"
