"""The message contract between the Orchestrator and the agents, v1.0.0 (agents/contract_agent.md), as the Data agent reads it.

Nine kinds of message share one header of ten fields; only `body.spec` (DISPATCH) and `body.ext` (REPORT) belong to the
agent, so they stay plain dicts here and each agent validates its own. Every model is closed (`extra="forbid"`): a receiver
refuses a message with a missing or an unknown field, as the contract says. Replies are `COMMAND_ACK`, `REPORT_ACK` and
`STATUS`, which carry `response_type` instead of a header.

This is the wire format. The internal `StepSpec@1` / `AgentReport@1` (messages.py, reports.py) are what the agents in this
repository speak today; an agent that wants to be called either way converts at its door.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from vdagent_contracts.scope import AuthorizedScope

CONTRACT_VERSION = "1.0.0"

FROZEN = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

AgentName = Literal["DATA", "COMPARE", "INSIGHT", "CHART", "REPORT"]
MessageType = Literal["DISPATCH", "START", "REWIRE", "RELEASE", "CANCEL", "ANSWER", "STATUS_QUERY", "FORWARD", "REPORT"]
ErrorClassName = Literal["NEED_INPUT", "WRONG_RESULT", "SPEC_ISSUE", "NO_DATA", "NO_ACCESS", "DATA_QUALITY",
                         "QUOTA_EXHAUSTED", "TRANSIENT", "FATAL", "CANCELED"]
ReasonClass = Literal["NEED_INPUT", "WRONG_RESULT", "SPEC_ISSUE", "NO_DATA", "NO_ACCESS", "DATA_QUALITY", "QUOTA_EXHAUSTED",
                      "TRANSIENT", "FATAL", "CANCELED", "TIMEOUT", "DELIVERY_FAILED", "DROPPED_BY_PLAN"]
TaskKind = Literal["LOOKUP", "COMPARE", "TREND", "EXPLAIN"]
RejectCode = Literal["UNSUPPORTED_CONTRACT_VERSION", "MALFORMED_MESSAGE", "UNKNOWN_MESSAGE_TYPE", "UNKNOWN_STEP", "WRONG_AGENT"]

SEMVER = r"^\d+\.\d+\.\d+$"
SNAKE = r"^[a-z][a-z0-9_]*$"
UPPER = r"^[A-Z][A-Z0-9_]*$"
ERROR_CODE = r"^[A-Z][A-Z0-9_-]*$"  # the contract's own examples use codes such as DEP-001
STEP_ID = r"^B[1-9][0-9]*$"

StepId = Annotated[str, Field(pattern=STEP_ID)]
Snake = Annotated[str, Field(pattern=SNAKE)]
UpperCode = Annotated[str, Field(pattern=UPPER)]


class Trace(BaseModel):
    model_config = FROZEN

    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None


# ---- shared types (§5) -----------------------------------------------------------------------------------------------


class PackageRef(BaseModel):
    """A result package: one immutable version. Never carries data."""

    model_config = FROZEN

    package_id: str = Field(min_length=1, max_length=200)
    kind: Snake
    status: Literal["VALID", "PARTIAL"]
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class WaitItem(BaseModel):
    model_config = FROZEN

    step_id: StepId
    agent: AgentName
    operation: Snake
    dependency: Literal["HARD", "SOFT"]
    purpose: Literal["INPUT", "SNAPSHOT_ONLY"]
    input_slot: Snake | None
    expected_kind: Snake | None

    @model_validator(mode="after")
    def _snapshot_only(self) -> WaitItem:
        if self.purpose == "SNAPSHOT_ONLY" and (self.dependency != "SOFT" or self.input_slot is not None or self.expected_kind is not None):
            raise ValueError("purpose SNAPSHOT_ONLY needs dependency SOFT and no input_slot or expected_kind")
        return self


class ForwardTarget(BaseModel):
    model_config = FROZEN

    step_id: StepId
    agent: AgentName


class InputArrival(BaseModel):
    model_config = FROZEN

    from_step_id: StepId
    from_agent: AgentName
    package: PackageRef


class ProvidedInput(BaseModel):
    model_config = FROZEN

    source_run_id: str
    source_step_id: StepId
    source_agent: AgentName
    input_slot: Snake
    package: PackageRef


class MissingPart(BaseModel):
    model_config = FROZEN

    step_id: StepId
    agent: AgentName
    part_label: str = Field(max_length=80)
    root_step_id: StepId
    reason_class: ReasonClass
    error_code: str | None
    user_message: str = Field(max_length=300)


class UserContext(BaseModel):
    """The caller as the contract writes it: `{user_id, role, authorized_scope, signature?}` (§5)."""

    model_config = FROZEN

    user_id: str
    role: Literal["SALES_OPS", "SALES_MANAGER", "PROJECT_DIRECTOR", "DATA_ANALYST"] = "SALES_OPS"
    authorized_scope: AuthorizedScope = Field(default_factory=AuthorizedScope)
    signature: str | None = None


class Warning(BaseModel):  # noqa: A001 - the contract's own name
    model_config = FROZEN

    code: Annotated[str, Field(pattern=ERROR_CODE)]
    message: str = Field(max_length=300)
    target: str | None = None
    details: dict[str, Any] | None = None


class ErrorInfo(BaseModel):
    model_config = FROZEN

    code: Annotated[str, Field(pattern=ERROR_CODE)]
    class_: ErrorClassName | None = Field(default=None, alias="class")
    reason: str = Field(min_length=1, max_length=1000)
    details: dict[str, Any] | None = None


class QuestionOption(BaseModel):
    model_config = FROZEN

    option_id: str = Field(min_length=1, max_length=64)
    label: str = Field(max_length=200)
    value: dict[str, Any] | None = None


class Question(BaseModel):
    model_config = FROZEN

    question_id: str = Field(min_length=1, max_length=64)
    reason_code: UpperCode
    text: str = Field(max_length=500)
    options: list[QuestionOption] = Field(min_length=1, max_length=10)
    max_selections: int = Field(default=1, ge=1)
    subject_text: str | None = Field(default=None, max_length=200)


class Usage(BaseModel):
    model_config = FROZEN

    llm_calls: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    cost_usd: str | None = None


class Progress(BaseModel):
    model_config = FROZEN

    stage: UpperCode
    stage_index: int | None = Field(default=None, ge=0)
    stage_count: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=300)


class DoneResult(BaseModel):
    model_config = FROZEN

    package: PackageRef
    snapshot_id: str | None
    summary: str = Field(max_length=800)
    warnings: list[Warning]


class Reject(BaseModel):
    model_config = FROZEN

    code: RejectCode
    message: str = Field(max_length=300)


# ---- bodies (§6) -----------------------------------------------------------------------------------------------------


class DispatchBody(BaseModel):
    model_config = FROZEN

    operation: Snake
    catalog_version: str = Field(pattern=SEMVER)
    plan_version: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=500)
    original_question: str = Field(min_length=1, max_length=2000)
    task_kinds: list[TaskKind] = Field(min_length=1)
    locale: str | None = None
    user_context: UserContext
    conversation_id: str | None
    parent_run_id: str | None
    snapshot_id: str | None
    deadline_s: int = Field(ge=1)
    wait_list: list[WaitItem]
    forward_to: list[ForwardTarget]
    provided_inputs: list[ProvidedInput] | None = None
    replaces_step_id: StepId | None = None
    retry_kind: Literal["NONE", "REPLAN", "USER_RETRY"] = "NONE"
    spec: dict[str, Any]


class StartBody(BaseModel):
    model_config = FROZEN

    snapshot_id: str | None
    inputs: list[InputArrival]
    released: list[MissingPart] | None = None


class RewireBody(BaseModel):
    model_config = FROZEN

    old_step_id: StepId
    new_step_id: StepId
    new_agent: AgentName
    new_operation: Snake


class ReleaseBody(BaseModel):
    model_config = FROZEN

    missing: MissingPart


class CancelBody(BaseModel):
    model_config = FROZEN

    scope: Literal["STEP", "RUN"]
    reason: Literal["USER_CANCELED", "RUN_DEADLINE", "STEP_TIMEOUT", "UPSTREAM_FAILED", "DROPPED_BY_PLAN", "INPUT_EXPIRED",
                    "INPUT_DECLINED", "QUESTION_LIMIT"]
    message: str | None = Field(default=None, max_length=300)


class AnswerBody(BaseModel):
    model_config = FROZEN

    question_id: str = Field(min_length=1, max_length=64)
    selected_option_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(min_length=1)
    answered_by: str
    answered_at: str


class StatusQueryBody(BaseModel):
    model_config = FROZEN

    agent_ref: str


class ForwardBody(BaseModel):
    model_config = FROZEN

    from_step_id: StepId
    from_agent: AgentName
    package: PackageRef
    snapshot_id: str


class ReportBody(BaseModel):
    """A report carries exactly the block of its kind: progress, result, error or question."""

    model_config = FROZEN

    kind: Literal["PROGRESS", "DONE", "ERROR", "QUESTION"]
    agent_state: str = Field(max_length=40)
    agent_ref: str | None = None
    usage: Usage | None = None
    progress: Progress | None = None
    result: DoneResult | None = None
    error: ErrorInfo | None = None
    question: Question | None = None
    ext: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_block(self) -> ReportBody:
        block = {"PROGRESS": "progress", "DONE": "result", "ERROR": "error", "QUESTION": "question"}[self.kind]
        for name in ("progress", "result", "error", "question"):
            present = getattr(self, name) is not None
            if name == block and not present:
                raise ValueError(f"a {self.kind} report needs its `{name}` block")
            if name != block and present:
                raise ValueError(f"a {self.kind} report must not carry `{name}`")
        return self


# ---- messages (§4) ---------------------------------------------------------------------------------------------------


def _rfc3339(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"sent_at must be an RFC 3339 UTC time, got {value!r}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"sent_at must carry a UTC offset, got {value!r}")
    return value


class Header(BaseModel):
    model_config = FROZEN

    contract_version: str = Field(pattern=SEMVER)
    message_id: str = Field(min_length=1, max_length=64)
    sent_at: str
    message_type: MessageType
    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    step_id: StepId
    agent: AgentName
    idempotency_key: str
    trace: Trace | None = None

    @model_validator(mode="after")
    def _checks(self) -> Header:
        _rfc3339(self.sent_at)
        if self.idempotency_key != f"{self.plan_id}:{self.step_id}":
            raise ValueError("idempotency_key must be plan_id:step_id")
        return self


class DispatchMessage(Header):
    message_type: Literal["DISPATCH"]
    body: DispatchBody


class StartMessage(Header):
    message_type: Literal["START"]
    body: StartBody


class RewireMessage(Header):
    message_type: Literal["REWIRE"]
    body: RewireBody


class ReleaseMessage(Header):
    message_type: Literal["RELEASE"]
    body: ReleaseBody


class CancelMessage(Header):
    message_type: Literal["CANCEL"]
    body: CancelBody


class AnswerMessage(Header):
    message_type: Literal["ANSWER"]
    body: AnswerBody


class StatusQueryMessage(Header):
    message_type: Literal["STATUS_QUERY"]
    body: StatusQueryBody


class ForwardMessage(Header):
    message_type: Literal["FORWARD"]
    body: ForwardBody


class ReportMessage(Header):
    message_type: Literal["REPORT"]
    body: ReportBody


Message = Annotated[
    DispatchMessage | StartMessage | RewireMessage | ReleaseMessage | CancelMessage | AnswerMessage | StatusQueryMessage
    | ForwardMessage | ReportMessage,
    Field(discriminator="message_type"),
]
_MESSAGE = TypeAdapter(Message)


def parse_message(data: dict[str, Any]) -> DispatchMessage | StartMessage | RewireMessage | ReleaseMessage | CancelMessage | AnswerMessage | StatusQueryMessage | ForwardMessage | ReportMessage:
    """The message, validated strictly. Raises `pydantic.ValidationError`."""
    return _MESSAGE.validate_python(data)


# ---- replies (§6.3) --------------------------------------------------------------------------------------------------


class _Ack(BaseModel):
    model_config = FROZEN

    contract_version: str = Field(default=CONTRACT_VERSION, pattern=SEMVER)
    in_reply_to: str = Field(min_length=1, max_length=64)
    reject: Reject | None = None

    def _check_reject(self, status: str) -> None:
        if (status == "REJECTED") != (self.reject is not None):
            raise ValueError("`reject` is required with REJECTED and forbidden otherwise")


class CommandAck(_Ack):
    response_type: Literal["COMMAND_ACK"] = "COMMAND_ACK"
    ack_status: Literal["ACCEPTED", "DUPLICATE", "REJECTED"]
    agent_ref: str | None = None

    @model_validator(mode="after")
    def _reject(self) -> CommandAck:
        self._check_reject(self.ack_status)
        return self


class ReportAck(_Ack):
    response_type: Literal["REPORT_ACK"] = "REPORT_ACK"
    ack_status: Literal["ACCEPTED", "DUPLICATE", "STALE", "REJECTED"]

    @model_validator(mode="after")
    def _reject(self) -> ReportAck:
        self._check_reject(self.ack_status)
        return self


class Status(BaseModel):
    model_config = FROZEN

    contract_version: str = Field(default=CONTRACT_VERSION, pattern=SEMVER)
    response_type: Literal["STATUS"] = "STATUS"
    in_reply_to: str = Field(min_length=1, max_length=64)
    agent_state: str = Field(max_length=40)
    last_report: ReportBody | None


_SEMVER = re.compile(SEMVER)


def supports(contract_version: str) -> bool:
    """True when this build speaks the MAJOR version of `contract_version`."""
    return bool(_SEMVER.match(contract_version)) and contract_version.split(".")[0] == CONTRACT_VERSION.split(".")[0]
