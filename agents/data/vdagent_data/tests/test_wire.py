"""The door of the Data agent for the Orchestrator contract v1.0 (contract_agent.md): what comes in (DISPATCH, ANSWER, START,
CANCEL, STATUS_QUERY, and what is refused) and what goes out (REPORT DONE / ERROR / QUESTION, COMMAND_ACK, STATUS).

Every reply is validated with the contract's own models; the examples E01, E07, E09, E11, E12 of the contract are the inputs.
Runs on the Backend's real MCP tools over a freshly built `re_warehouse` (see conftest); no LLM.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from vdagent_data.contract_v1 import CommandAck, ReportMessage, Status, parse_message
from vdagent_data.tests.conftest import ALICE, BOB, McpPort
from vdagent_data.v1 import ERROR_TABLE
from vdagent_data.wire import Door, confidence, is_v1, map_warning

EXAMPLES = {e["id"]: e["message"] for e in json.loads((Path(__file__).parent / "fixtures" / "orch_v1_examples.json").read_text(encoding="utf-8"))}
TABLE_D = {"SPEC_MISMATCH", "SPEC_INVALID", "DATA_UNAVAILABLE", "EMPTY_RESULT", "OUT_OF_SCOPE", "DQ_BLOCKING", "RESULT_TRUNCATED", "BUDGET_EXCEEDED",
           "CONFIG_MISSING", "ID_CONFLICT", "LLM_UNAVAILABLE", "LLM_QUOTA", "WORKER_LOST", "CANCELED"}
WARNING_CODES = {"PROVISIONAL_DEFINITION", "SPEC_DOUBT", "SMALL_SAMPLE", "LOW_CONFIDENCE", "EMPTY_RESULT", "BUDGET_EXCEEDED", "LIMITATION", "T3_CAP_REACHED"}


def dispatch(spec: dict[str, Any] | None = None, *, operation: str = "fetch_units", step_id: str = "B1", user: str = ALICE,
             question: str = "Tại sao phân khu Landmark bán chậm?", **body: Any) -> dict[str, Any]:
    """The contract's E01 with a caller that exists in the test DB."""
    m = copy.deepcopy(EXAMPLES["E01"])
    m["step_id"], m["idempotency_key"] = step_id, f"{m['plan_id']}:{step_id}"
    m["message_id"] = f"cmd-{step_id}-{abs(hash(json.dumps(spec, sort_keys=True, default=str))) % 10**6}"
    b = m["body"]
    b.update(operation=operation, original_question=question, forward_to=[])
    b["user_context"] = {"user_id": user, "role": "SALES_OPS", "authorized_scope": {"project_ids": [], "zone_ids": []}}
    if spec is not None:
        b["spec"] = spec
    b.update(body)
    return m


def ent(mention: str, hint: str = "UNKNOWN") -> dict[str, str]:
    return {"mention": mention, "kind_hint": hint}


async def send(door: Door, port: McpPort, message: dict[str, Any]) -> dict[str, Any]:
    reply = await door.handle(json.dumps(message, ensure_ascii=False), port)
    return reply.message


def report_of(reply: dict[str, Any]) -> ReportMessage:
    parsed = parse_message(reply)  # the reply must be a valid contract message
    assert isinstance(parsed, ReportMessage), reply
    return parsed


# ---- telling a v1.0 message from the rest ---------------------------------------------------------------------------------------


def test_only_a_json_object_with_contract_version_and_message_type_is_v1() -> None:
    assert is_v1(json.dumps(EXAMPLES["E01"]))
    assert is_v1("[from: orchestrator] " + json.dumps(EXAMPLES["E01"]))
    assert not is_v1(json.dumps({"contract": "StepSpec@1", "run_id": "r"}))
    assert not is_v1("Tại sao phân khu Landmark bán chậm?")
    assert not is_v1("{not json")
    assert not is_v1(json.dumps({"contract_version": "1.0.0"}))


# ---- DISPATCH to DONE --------------------------------------------------------------------------------------------------------


async def test_a_dispatch_for_one_unit_is_answered_with_one_conformant_done(alice: McpPort) -> None:
    reply = await send(Door(), alice, dispatch({"entities": [ent("A12-08", "UNIT")]}, question="Vì sao căn A12-08 bán chậm?"))
    message = report_of(reply)
    assert (message.run_id, message.step_id, message.agent, message.idempotency_key) == (
        EXAMPLES["E01"]["run_id"], "B1", "DATA", EXAMPLES["E01"]["plan_id"] + ":B1")
    assert message.trace is not None and message.trace.trace_id == EXAMPLES["E01"]["trace"]["trace_id"]
    body = message.body
    assert body.kind == "DONE" and body.agent_state == "completed" and body.result is not None
    result = body.result
    assert result.snapshot_id == "SNAP-2026-09-28"  # locked by Data: the dispatch carried none
    assert result.package.kind == "unit_set" and result.package.status in ("VALID", "PARTIAL")
    stored = await alice.call("artifact_get", {"artifact_id": result.package.package_id.split("@")[0], "version": int(result.package.package_id.split("@")[1])})
    assert stored["artifact_type"] == "dataset" and stored["content_hash"] == result.package.content_hash
    assert 0 < len(result.summary) <= 800
    assert body.ext is not None
    related = {p["kind"]: p for p in body.ext["related_packages"]}
    assert set(related) == {"metric", "dq"} and all(len(p["content_hash"]) == 64 for p in related.values())
    assert body.ext["data_confidence"]["level"] in ("HIGH", "MEDIUM", "LOW") and body.ext["data_confidence"]["reasons"]
    assert body.ext["entities_resolved"][0]["kind"] == "UNIT" and body.usage is not None and body.usage.llm_calls == 0


async def test_every_warning_is_a_typed_object_of_the_contract(alice: McpPort) -> None:
    reply = await send(Door(), alice, dispatch({"entities": [ent("A12-08", "UNIT")]}))
    warnings = report_of(reply).body.result.warnings  # type: ignore[union-attr]
    assert warnings and all(w.code in WARNING_CODES and 0 < len(w.message) <= 300 for w in warnings)
    assert any(w.code == "LIMITATION" and w.target for w in warnings)


async def test_aggregate_metrics_is_a_metric_table_package_with_the_dataset_beside_it(alice: McpPort) -> None:
    reply = await send(Door(), alice, dispatch({"scope_all": True, "metrics": ["unit_count", "slow_moving_rate"], "group_by": ["zone"]},
                                               operation="aggregate_metrics", question="Tỷ lệ bán chậm theo phân khu?"))
    body = report_of(reply).body
    assert body.kind == "DONE" and body.result is not None and body.result.package.kind == "metric_table"
    assert body.ext is not None and {p["kind"] for p in body.ext["related_packages"]} == {"dataset", "dq"}


async def test_the_reply_to_a_step_with_a_given_snapshot_keeps_it(alice: McpPort) -> None:
    reply = await send(Door(), alice, dispatch({"entities": [ent("A12-08", "UNIT")]}, snapshot_id="SNAP-2026-08-31"))
    assert report_of(reply).body.result.snapshot_id == "SNAP-2026-08-31"  # type: ignore[union-attr]


# ---- QUESTION and ANSWER -----------------------------------------------------------------------------------------------------


async def test_the_contracts_own_landmark_dispatch_asks_which_zone_and_the_answer_finishes_the_step(alice: McpPort) -> None:
    door = Door()
    first = report_of(await send(door, alice, dispatch()))  # the spec of E01: the mention "phân khu Landmark", hint ZONE
    body = first.body
    assert body.kind == "QUESTION" and body.agent_state == "input_required" and body.question is not None
    q = body.question
    assert q.reason_code == "AMBIGUOUS_REQUEST" and q.subject_text == "phân khu Landmark" and q.max_selections == 1
    assert [o.value["entity_kind"] for o in q.options] == ["ZONE", "ZONE"] and {o.value["entity_id"] for o in q.options} == {"ZN-A", "ZN-B"}
    assert all(o.label and o.value["display_name"] for o in q.options)
    assert (await alice.call("artifact_list", {}))["artifacts"] == []  # a question stores nothing

    chosen = next(o for o in q.options if o.value["entity_id"] == "ZN-B")
    answer = copy.deepcopy(EXAMPLES["E11"])
    answer["body"].update(question_id=q.question_id, selected_option_ids=[chosen.option_id], answered_by=ALICE)
    done = report_of(await send(door, alice, answer))
    assert done.body.kind == "DONE" and done.body.ext is not None
    assert done.body.ext["entities_resolved"][0]["id"] == "ZN-B" and done.body.ext["entities_resolved"][0]["method"] == "saved_choice"


async def test_the_choice_is_remembered_for_the_next_step_of_the_run(alice: McpPort) -> None:
    door = Door()
    q = report_of(await send(door, alice, dispatch())).body.question
    assert q is not None
    answer = copy.deepcopy(EXAMPLES["E11"])
    answer["body"].update(question_id=q.question_id, selected_option_ids=[q.options[0].option_id], answered_by=ALICE)
    await send(door, alice, answer)
    second = report_of(await send(door, alice, dispatch(step_id="B2")))  # same run, same mention: not asked again
    assert second.body.kind == "DONE"


@pytest.mark.parametrize("patch", [{"question_id": "q-other"}, {"selected_option_ids": ["opt-not-offered"]}])
async def test_an_answer_that_matches_no_question_is_rejected(alice: McpPort, patch: dict[str, Any]) -> None:
    door = Door()
    q = report_of(await send(door, alice, dispatch())).body.question
    assert q is not None
    answer = copy.deepcopy(EXAMPLES["E11"])
    answer["body"].update(question_id=q.question_id, selected_option_ids=[q.options[0].option_id], answered_by=ALICE)
    answer["body"].update(patch)
    ack = CommandAck.model_validate(await send(door, alice, answer))
    assert ack.ack_status == "REJECTED" and ack.reject is not None and ack.reject.code in ("UNKNOWN_STEP", "MALFORMED_MESSAGE")


async def test_an_unknown_unit_asks_with_the_nearest_codes(alice: McpPort) -> None:
    reply = await send(Door(), alice, dispatch({"entities": [ent("A12-09", "UNIT")]}, question="Vì sao căn A12-09 bán chậm?"))
    q = report_of(reply).body.question
    assert q is not None and q.reason_code == "ENTITY_NOT_FOUND" and "A12-08" in [o.value["display_name"] for o in q.options]


# ---- ERROR -------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec,code,klass,state,changes", [
    ({"scope_all": True, "metrics": ["profit"]}, "SPEC_INVALID", "SPEC_ISSUE", "rejected", {"operation": "aggregate_metrics"}),
    ({"entities": [ent("A12-08", "UNIT")]}, "DQ_BLOCKING", "DATA_QUALITY", "failed", {"snapshot_id": "SNAP-2026-09-29"}),
    ({"entities": [ent("A12-08", "UNIT")]}, "DQ_BLOCKING", "DATA_QUALITY", "failed", {"snapshot_id": "SNAP-NOPE"}),
    ({"scope_all": True, "filters": ["available", "sold"]}, "EMPTY_RESULT", "NO_DATA", "failed", {}),
    ({"entities": [ent("qqqqqq", "ZONE")]}, "OUT_OF_SCOPE", "NO_ACCESS", "rejected", {}),
    ({"entities": [ent("A12-08", "UNIT")]}, "SPEC_INVALID", "SPEC_ISSUE", "rejected", {"catalog_version": "2.0.0"}),
    ({"entities": [ent("A12-08", "UNIT")]}, "SPEC_INVALID", "SPEC_ISSUE", "rejected", {"operation": "delete_units"}),
])
async def test_a_refusal_carries_the_contracts_code_class_and_state(alice: McpPort, spec: dict[str, Any], code: str, klass: str, state: str,
                                                                   changes: dict[str, Any]) -> None:
    body = report_of(await send(Door(), alice, dispatch(spec, **changes))).body
    assert body.kind == "ERROR" and body.error is not None
    assert (body.error.code, body.error.class_, body.agent_state) == (code, klass, state)
    assert 0 < len(body.error.reason) <= 1000


async def test_a_step_of_someone_else_is_out_of_scope(alice: McpPort) -> None:
    body = report_of(await send(Door(), alice, dispatch({"scope_all": True}, user=BOB))).body
    assert body.error is not None and (body.error.code, body.error.class_) == ("OUT_OF_SCOPE", "NO_ACCESS")


def test_every_code_the_agent_can_raise_becomes_a_code_of_the_contract_table() -> None:
    mapped = {contract for contract, _ in ERROR_TABLE.values()}
    assert mapped <= TABLE_D | {"INTERNAL_ERROR"}  # INTERNAL_ERROR is not in the table: FATAL by the Orchestrator's own rule
    assert {"SPEC_INVALID", "DQ_BLOCKING", "EMPTY_RESULT", "OUT_OF_SCOPE", "RESULT_TRUNCATED", "CONFIG_MISSING", "WORKER_LOST"} <= mapped


async def test_a_step_that_outlives_its_deadline_stops_with_budget_exceeded(alice: McpPort) -> None:
    class Slow:
        calls: list[str] = []

        async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(5)
            return await alice.call(name, args)

    body = report_of(await send(Door(), Slow(), dispatch({"entities": [ent("A12-08", "UNIT")]}, deadline_s=1))).body  # type: ignore[arg-type]
    assert body.error is not None and (body.error.code, body.error.class_) == ("BUDGET_EXCEEDED", "SPEC_ISSUE")


# ---- the step waits for what this build cannot receive ------------------------------------------------------------------------


async def test_a_step_that_waits_for_an_input_package_is_refused_not_run_half_blind(alice: McpPort) -> None:
    wait = [{"step_id": "B9", "agent": "DATA", "operation": "fetch_units", "dependency": "HARD", "purpose": "INPUT",
             "input_slot": "input_artifact_refs", "expected_kind": "unit_set"}]
    body = report_of(await send(Door(), alice, dispatch({"entities": [ent("A12-08", "UNIT")]}, wait_list=wait))).body
    assert body.error is not None and body.error.code == "SPEC_INVALID" and "input" in body.error.reason.lower()


async def test_a_wait_only_for_the_snapshot_does_not_block_the_step(alice: McpPort) -> None:
    wait = [{"step_id": "B9", "agent": "DATA", "operation": "fetch_units", "dependency": "SOFT", "purpose": "SNAPSHOT_ONLY",
             "input_slot": None, "expected_kind": None}]
    body = report_of(await send(Door(), alice, dispatch({"entities": [ent("A12-08", "UNIT")]}, wait_list=wait))).body
    assert body.kind == "DONE"


# ---- the same key twice -------------------------------------------------------------------------------------------------------


async def test_the_same_dispatch_twice_gets_the_same_answer_without_reading_again(alice: McpPort) -> None:
    door = Door()
    message = dispatch({"entities": [ent("A12-08", "UNIT")]})
    first = await send(door, alice, message)
    reads = len(alice.calls)
    second = await send(door, alice, message)
    assert len(alice.calls) == reads  # nothing was read or written again
    assert report_of(second).body.result.package == report_of(first).body.result.package  # type: ignore[union-attr]
    assert second["message_id"] != first["message_id"]


async def test_the_same_key_with_another_content_is_an_id_conflict(alice: McpPort) -> None:
    door = Door()
    await send(door, alice, dispatch({"entities": [ent("A12-08", "UNIT")]}))
    other = dispatch({"entities": [ent("A12-11", "UNIT")]})
    body = report_of(await send(door, alice, other)).body
    assert body.error is not None and (body.error.code, body.error.class_, body.agent_state) == ("ID_CONFLICT", "FATAL", "rejected")


async def test_a_user_retry_runs_again(alice: McpPort) -> None:
    door = Door()
    message = dispatch({"entities": [ent("A12-08", "UNIT")]})
    await send(door, alice, message)
    reads = len(alice.calls)
    retry = {**message, "message_id": "cmd-retry", "body": {**message["body"], "retry_kind": "USER_RETRY"}}
    assert report_of(await send(door, alice, retry)).body.kind == "DONE" and len(alice.calls) > reads


# ---- the other messages ------------------------------------------------------------------------------------------------------


async def test_start_and_cancel_are_acknowledged_for_a_known_step_and_refused_for_an_unknown_one(alice: McpPort) -> None:
    door = Door()
    start = EXAMPLES["E07"]
    unknown = CommandAck.model_validate(await send(door, alice, start))
    assert unknown.ack_status == "REJECTED" and unknown.reject is not None and unknown.reject.code == "UNKNOWN_STEP" and unknown.in_reply_to == start["message_id"]
    await send(door, alice, dispatch({"entities": [ent("A12-08", "UNIT")]}))
    assert CommandAck.model_validate(await send(door, alice, start)).ack_status == "ACCEPTED"
    cancel = {**start, "message_id": "cmd-cancel", "message_type": "CANCEL", "body": {"scope": "STEP", "reason": "USER_CANCELED"}}
    assert CommandAck.model_validate(await send(door, alice, cancel)).ack_status == "ACCEPTED"


async def test_a_status_query_returns_the_last_report(alice: McpPort) -> None:
    door = Door()
    done = await send(door, alice, dispatch({"entities": [ent("A12-08", "UNIT")]}))
    ref = done["body"]["agent_ref"]
    query = {**EXAMPLES["E07"], "message_id": "cmd-status", "message_type": "STATUS_QUERY", "body": {"agent_ref": ref}}
    status = Status.model_validate(await send(door, alice, query))
    assert status.agent_state == "completed" and status.last_report is not None and status.last_report.kind == "DONE" and status.in_reply_to == "cmd-status"


@pytest.mark.parametrize("example", ["E18", "E20", "E13", "E12"])  # REWIRE, RELEASE, FORWARD, REPORT of the contract
async def test_the_asynchronous_messages_are_refused_plainly(alice: McpPort, example: str) -> None:
    message = {**copy.deepcopy(EXAMPLES[example]), "agent": "DATA"}
    ack = CommandAck.model_validate(await send(Door(), alice, message))
    assert ack.ack_status == "REJECTED" and ack.reject is not None and ack.reject.code == "UNKNOWN_MESSAGE_TYPE"


# ---- a message that is not valid ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("edit,code", [
    (lambda m: m["body"].pop("original_question"), "MALFORMED_MESSAGE"),
    (lambda m: m.update(unexpected=True), "MALFORMED_MESSAGE"),
    (lambda m: m.update(step_id="3"), "MALFORMED_MESSAGE"),
    (lambda m: m.update(message_type="PING"), "UNKNOWN_MESSAGE_TYPE"),
    (lambda m: m.update(contract_version="2.0.0"), "UNSUPPORTED_CONTRACT_VERSION"),
    (lambda m: m.update(agent="INSIGHT"), "WRONG_AGENT"),
])
async def test_a_message_that_breaks_the_contract_is_rejected_with_its_reason(alice: McpPort, edit: Any, code: str) -> None:
    message = dispatch({"entities": [ent("A12-08", "UNIT")]})
    edit(message)
    ack = CommandAck.model_validate(await send(Door(), alice, message))
    assert ack.ack_status == "REJECTED" and ack.reject is not None and ack.reject.code == code and ack.in_reply_to == message["message_id"]
    assert len(ack.reject.message) <= 300
    assert alice.calls == []  # nothing was read


# ---- confidence and warnings -------------------------------------------------------------------------------------------------


def test_confidence_is_high_without_limits_medium_with_provisional_or_assumed_and_low_with_missing_data() -> None:
    assert confidence([]).level == "HIGH" and confidence([]).reasons
    for w in ("PROVISIONAL_DEFINITION:absorption_rate", "CONFIG_PENDING:min_group_size", "SYNTHETIC_SOURCE:net_area_m2", "SNAPSHOT_STATUS_ASSUMED",
              "SMALL_SAMPLE:3", "OUT_OF_CATALOG_NEED_NOT_SERVED"):
        assert confidence([w]).level == "MEDIUM", w
    for w in ("METRIC_UNAVAILABLE:discount_pct", "DQ_MISSING:net_price_per_m2:4", "WINDOW_INCOMPLETE:inquiry_leads_30d:2", "PEER_AREA_UNAVAILABLE:1"):
        assert confidence(["SNAPSHOT_STATUS_ASSUMED", w]).level == "LOW", w
    assert all(0 < len(r) <= 200 for r in confidence(["METRIC_UNAVAILABLE:x", "SNAPSHOT_STATUS_ASSUMED"]).reasons)


@pytest.mark.parametrize("raw,code,target", [
    ("PROVISIONAL_DEFINITION:absorption_rate", "PROVISIONAL_DEFINITION", "absorption_rate"),
    ("CONFIG_PENDING:min_group_size", "PROVISIONAL_DEFINITION", "min_group_size"),
    ("EMPTY_RESULT", "EMPTY_RESULT", None),
    ("SMALL_SAMPLE:3", "SMALL_SAMPLE", None),
    ("METRIC_UNAVAILABLE:discount_pct", "LIMITATION", "discount_pct"),
    ("WINDOW_INCOMPLETE:inquiry_leads_30d:2", "LIMITATION", "inquiry_leads_30d"),
    ("DQ_MISSING:net_price_per_m2:4", "LIMITATION", "net_price_per_m2"),
    ("PEER_AREA_UNAVAILABLE:1", "LIMITATION", None),
    ("SYNTHETIC_SOURCE:net_area_m2", "LIMITATION", "net_area_m2"),
    ("SNAPSHOT_STATUS_ASSUMED", "LIMITATION", "snapshot"),
    ("SOMETHING_NEW:x", "LIMITATION", None),
])
def test_an_internal_warning_becomes_a_typed_warning_that_keeps_the_original(raw: str, code: str, target: str | None) -> None:
    w = map_warning(raw)
    assert w["code"] == code and w.get("target") == target and 0 < len(w["message"]) <= 300
    assert w["details"]["raw"] == raw


def test_every_operation_of_the_agent_has_a_package_kind() -> None:
    from vdagent_data.v1 import OPERATIONS  # noqa: PLC0415
    from vdagent_data.wire import PACKAGE_OF_OPERATION  # noqa: PLC0415

    assert set(PACKAGE_OF_OPERATION) == set(OPERATIONS)
    assert {kind for _, kind in PACKAGE_OF_OPERATION.values()} == {"unit_set", "metric_table", "peer_set", "context_bundle"}
