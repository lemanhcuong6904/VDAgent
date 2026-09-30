import json

import pytest
from pydantic import ValidationError

from vdagent_contracts.messages import ContractMessage, FreeText, StepSpec, parse_incoming
from vdagent_contracts.reports import AgentReport, ParseError, parse_agent_report, render_agent_report


def _report(**overrides: object) -> AgentReport:
    fields: dict[str, object] = {
        "run_id": "t_1",
        "step_id": "B1",
        "idempotency_key": "PLAN-1:B1",
        "state": "completed",
        "artifact_refs": [{"artifact_id": "art_1", "version": 1, "artifact_type": "data_package"}],
        "snapshot_id": "SNAP-1",
        "summary": "DOM trung bình 61 ngày.",
    }
    fields.update(overrides)
    return AgentReport.model_validate(fields)


def test_render_agent_report_roundtrip() -> None:
    report = _report(warnings=["SMALL_SAMPLE"], partial=True)
    text = render_agent_report("Đã lấy số liệu.", report)
    assert text.startswith("Đã lấy số liệu.")
    assert parse_agent_report(text) == report


def test_parse_agent_report_from_fenced_json() -> None:
    body = _report().model_dump(mode="json")
    text = f"Tóm tắt.\n\n```json\n{json.dumps(body, ensure_ascii=False)}\n```\n"
    parsed = parse_agent_report(text)
    assert isinstance(parsed, AgentReport)
    assert parsed.state == "completed"


def test_parse_agent_report_rejects_two_fences() -> None:
    body = json.dumps(_report().model_dump(mode="json"))
    result = parse_agent_report(f"```json\n{body}\n```\n```json\n{body}\n```")
    assert isinstance(result, ParseError)
    assert "exactly one" in result.reason


def test_parse_agent_report_bad_json_returns_parse_error() -> None:
    assert isinstance(parse_agent_report("```json\n{not json}\n```"), ParseError)
    assert isinstance(parse_agent_report("no fence at all"), ParseError)
    wrong = json.dumps({"contract": "AgentReport@1", "state": "done"})
    assert isinstance(parse_agent_report(f"```json\n{wrong}\n```"), ParseError)


def test_state_needs_matching_error_or_question() -> None:
    with pytest.raises(ValidationError):
        _report(state="failed")  # no error
    with pytest.raises(ValidationError):
        _report(state="input_required")  # no question
    with pytest.raises(ValidationError):
        _report(error={"code": "X", "message": "m", "retryable": False})  # completed with error


def test_question_options_have_ids() -> None:
    report = _report(
        state="input_required",
        question={"text": "Bạn muốn xem phân khu nào?", "options": [{"id": "Z-LM1", "label": "Tòa Landmark 1"}]},
    )
    assert report.question is not None
    assert report.question.options[0].id == "Z-LM1"
    with pytest.raises(ValidationError):
        _report(state="input_required", question={"text": "?", "options": [{"label": "không id"}]})


def _step_spec() -> dict[str, object]:
    return {
        "contract": "StepSpec@1",
        "run_id": "t_1",
        "plan_id": "PLAN-1",
        "step_id": "B1",
        "idempotency_key": "PLAN-1:B1",
        "operation": "aggregate_metrics",
        "spec": {"metrics": ["avg_dom_unsold"]},
        "user_context": {"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-X"]}},
        "deadline_s": 90,
        "original_question": "DOM trung bình của Landmark?",
    }


def test_incoming_message_json_contract_is_strict() -> None:
    incoming = parse_incoming("[from: orchestrator] " + json.dumps(_step_spec(), ensure_ascii=False))
    assert isinstance(incoming, ContractMessage)
    assert incoming.contract == "StepSpec@1"
    spec = StepSpec.model_validate(incoming.data)
    assert spec.snapshot_id is None
    with pytest.raises(ValidationError):
        StepSpec.model_validate({**_step_spec(), "idempotency_key": "PLAN-1:B2"})
    with pytest.raises(ValidationError):
        StepSpec.model_validate({**_step_spec(), "surprise": 1})
    with pytest.raises(ValueError):
        parse_incoming('{"no_contract": true}')


def test_incoming_free_text_is_user_question() -> None:
    incoming = parse_incoming("Tại sao căn A12-08 bán chậm?")
    assert incoming == FreeText(text="Tại sao căn A12-08 bán chậm?")
    assert isinstance(parse_incoming("{ không phải json"), FreeText)


def test_incoming_strips_from_prefix() -> None:
    assert parse_incoming("[from: insight] Cho tôi DOM của A12-08") == FreeText(text="Cho tôi DOM của A12-08")
