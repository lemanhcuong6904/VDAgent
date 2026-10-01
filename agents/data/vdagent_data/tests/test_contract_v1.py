"""The Orchestrator ↔ agent message contract v1.0 (agents/contract_agent.md).

The fixture holds the examples of that document (E01…E29): every one must parse, and re-serialising what was set must give
back exactly the same JSON (a model that drops or invents a field would break the round trip).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from vdagent_data.contract_v1 import (
    CONTRACT_VERSION,
    CommandAck,
    DispatchMessage,
    ReportMessage,
    parse_message,
)

EXAMPLES = json.loads((Path(__file__).parent / "fixtures" / "orch_v1_examples.json").read_text(encoding="utf-8"))
BY_ID = {e["id"]: e["message"] for e in EXAMPLES}


def dump(message: Any) -> dict[str, Any]:
    return json.loads(message.model_dump_json(by_alias=True, exclude_unset=True))


@pytest.mark.parametrize("example", EXAMPLES, ids=[e["id"] for e in EXAMPLES])
def test_every_example_of_the_contract_parses_and_round_trips(example: dict[str, Any]) -> None:
    message = parse_message(example["message"])
    assert dump(message) == example["message"]


def test_the_examples_cover_every_kind_of_message_the_data_agent_meets() -> None:
    kinds = {m["message_type"] for m in BY_ID.values()}
    assert {"DISPATCH", "START", "ANSWER", "REPORT"} <= kinds
    reports = {m["body"]["kind"] for m in BY_ID.values() if m["message_type"] == "REPORT"}
    assert {"DONE", "ERROR", "QUESTION"} <= reports


def test_the_version_is_the_documents() -> None:
    assert CONTRACT_VERSION == "1.0.0"


# ---- the header ------------------------------------------------------------------------------------------------------


def with_header(**changes: Any) -> dict[str, Any]:
    message = json.loads(json.dumps(BY_ID["E01"]))
    message.update(changes)
    return message


def test_the_idempotency_key_is_plan_and_step() -> None:
    with pytest.raises(ValidationError, match="idempotency_key"):
        parse_message(with_header(idempotency_key="pl-other:B1"))


@pytest.mark.parametrize("changes", [
    {"step_id": "3"},
    {"step_id": "B0"},
    {"agent": "data"},
    {"agent": "ORCHESTRATOR"},
    {"message_id": "x" * 65},
    {"sent_at": "yesterday"},
    {"contract_version": "one"},
    {"unexpected": True},
])
def test_a_malformed_header_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse_message(with_header(**changes))


def test_an_unknown_message_type_is_refused() -> None:
    with pytest.raises(ValidationError):
        parse_message(with_header(message_type="PING"))


# ---- DISPATCH --------------------------------------------------------------------------------------------------------


def test_a_dispatch_carries_what_the_data_agent_needs() -> None:
    message = parse_message(BY_ID["E01"])
    assert isinstance(message, DispatchMessage)
    body = message.body
    assert (body.operation, body.catalog_version, body.plan_version) == ("fetch_units", "1.0.0", 1)
    assert body.snapshot_id is None and body.wait_list == [] and [t.step_id for t in body.forward_to] == ["B2", "B3"]
    assert body.user_context.authorized_scope.project_ids == ["PRJ-X"]
    assert body.spec["entities"] == [{"mention": "phân khu Landmark", "kind_hint": "ZONE"}]
    assert body.retry_kind == "NONE" and body.task_kinds == ["EXPLAIN"]


@pytest.mark.parametrize("path,value", [
    (("body", "deadline_s"), 0),
    (("body", "plan_version"), 0),
    (("body", "task_kinds"), []),
    (("body", "task_kinds"), ["PLAN"]),
    (("body", "objective"), "x" * 501),
    (("body", "original_question"), "x" * 2001),
    (("body", "retry_kind"), "AGAIN"),
])
def test_a_dispatch_body_out_of_range_is_refused(path: tuple[str, str], value: Any) -> None:
    data = json.loads(json.dumps(BY_ID["E01"]))
    data[path[0]][path[1]] = value
    with pytest.raises(ValidationError):
        parse_message(data)


def test_a_dispatch_without_a_required_field_is_refused() -> None:
    data = json.loads(json.dumps(BY_ID["E01"]))
    del data["body"]["original_question"]
    with pytest.raises(ValidationError, match="original_question"):
        parse_message(data)


def test_a_wait_item_that_only_waits_for_the_snapshot_has_no_slot() -> None:
    data = json.loads(json.dumps(BY_ID["E01"]))
    data["body"]["wait_list"] = [{"step_id": "B1", "agent": "DATA", "operation": "fetch_units", "dependency": "SOFT",
                                  "purpose": "SNAPSHOT_ONLY", "input_slot": "input_artifact_refs", "expected_kind": None}]
    with pytest.raises(ValidationError, match="SNAPSHOT_ONLY"):
        parse_message(data)
    data["body"]["wait_list"][0].update(input_slot=None)
    assert parse_message(data).body.wait_list[0].purpose == "SNAPSHOT_ONLY"
    data["body"]["wait_list"][0].update(dependency="HARD")
    with pytest.raises(ValidationError, match="SNAPSHOT_ONLY"):
        parse_message(data)


# ---- REPORT ----------------------------------------------------------------------------------------------------------


def report(**body: Any) -> dict[str, Any]:
    data = json.loads(json.dumps(BY_ID["E12"]))
    data["body"] = body
    return data


DONE = json.loads(json.dumps(BY_ID["E12"]["body"]))


def test_a_done_report_carries_the_package_snapshot_and_confidence() -> None:
    message = parse_message(BY_ID["E12"])
    assert isinstance(message, ReportMessage)
    result = message.body.result
    assert result is not None and result.package.kind == "unit_set" and result.package.status == "VALID"
    assert result.snapshot_id == "SNAP-20260630-01" and message.body.ext == {"data_confidence": {"level": "HIGH", "reasons": ["Truy vấn T1, chỉ số approved"]}}


@pytest.mark.parametrize("body", [
    {"kind": "DONE", "agent_state": "completed"},  # no result
    {**DONE, "error": {"code": "X", "reason": "r"}},  # a block that does not belong to the kind
    {"kind": "ERROR", "agent_state": "failed"},  # no error
    {"kind": "QUESTION", "agent_state": "input_required"},  # no question
    {"kind": "PROGRESS", "agent_state": "working"},  # no progress
    {"kind": "DONE", "agent_state": "completed", "result": {**DONE["result"], "summary": "x" * 801}},
    {"kind": "DONE", "agent_state": "completed", "result": {**DONE["result"], "package": {**DONE["result"]["package"], "status": "DRAFT"}}},
    {"kind": "DONE", "agent_state": "completed", "result": {**DONE["result"], "warnings": [{"code": "low", "message": "m"}]}},
    {**DONE, "agent_state": "x" * 41},
])
def test_a_report_must_carry_exactly_the_block_of_its_kind(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse_message(report(**body))


def test_an_error_carries_a_code_and_a_reason_and_may_name_its_class() -> None:
    body = {"kind": "ERROR", "agent_state": "failed", "error": {"code": "SPEC_INVALID", "class": "SPEC_ISSUE", "reason": "sai khuôn"}}
    message = parse_message(report(**body))
    assert message.body.error is not None and message.body.error.class_ == "SPEC_ISSUE"
    assert dump(message)["body"]["error"]["class"] == "SPEC_ISSUE"  # the wire name is `class`
    with pytest.raises(ValidationError):
        parse_message(report(kind="ERROR", agent_state="failed", error={"code": "SPEC_INVALID", "class": "MYSTERY", "reason": "r"}))


def test_a_question_offers_one_to_ten_closed_options() -> None:
    question = json.loads(json.dumps(BY_ID["E09"]["body"]["question"]))
    parse_message(report(kind="QUESTION", agent_state="input_required", question=question))
    for options in ([], [{"option_id": f"o{i}", "label": "l"} for i in range(11)]):
        with pytest.raises(ValidationError):
            parse_message(report(kind="QUESTION", agent_state="input_required", question={**question, "options": options}))


# ---- the replies -----------------------------------------------------------------------------------------------------


def test_an_ack_is_accepted_duplicate_or_rejected_with_a_reason() -> None:
    ok = CommandAck(in_reply_to="cmd-1", ack_status="ACCEPTED", agent_ref="ref-1")
    assert json.loads(ok.model_dump_json(exclude_none=True)) == {
        "contract_version": "1.0.0", "response_type": "COMMAND_ACK", "in_reply_to": "cmd-1", "ack_status": "ACCEPTED", "agent_ref": "ref-1"}
    with pytest.raises(ValidationError):
        CommandAck(in_reply_to="cmd-1", ack_status="REJECTED")  # a rejection needs its reason
    rejected = CommandAck(in_reply_to="cmd-1", ack_status="REJECTED", reject={"code": "WRONG_AGENT", "message": "not mine"})
    assert rejected.reject is not None and rejected.reject.code == "WRONG_AGENT"
    with pytest.raises(ValidationError):
        CommandAck(in_reply_to="cmd-1", ack_status="ACCEPTED", reject={"code": "WRONG_AGENT", "message": "m"})
    with pytest.raises(ValidationError):
        CommandAck(in_reply_to="cmd-1", ack_status="REJECTED", reject={"code": "NOPE", "message": "m"})
