"""Unit codes of the DATA team's real warehouse (OCP-U00001, SMC-U…, VGP-U…, MAS-U…, TST-U…) plan like A12-08."""

from __future__ import annotations

import pytest

from vdagent_orchestrator.planner import UNIT_CODE, build_plan, classify, parse_request

PIN = {"snapshot_id": "SNAP-20260630-01", "semantic_config_version": "3.1.0"}


@pytest.mark.parametrize("code", ["OCP-U00001", "SMC-U03000", "VGP-U33619", "MAS-U05094", "TST-U00007"])
def test_a_real_unit_code_is_recognised(code: str) -> None:
    request = classify(f"Vì sao căn {code} bán chậm?", **PIN)
    assert request is not None and request.subject_unit_code == code and "explain" in request.wants
    plan = build_plan(request, "t_1")
    assert plan.steps[0].agent == "data" and plan.steps[0].spec["subject_unit_code"] == code


def test_the_mock_codes_and_the_structured_request_still_work() -> None:
    assert classify("Vì sao căn A12-08 bán chậm?", **PIN).subject_unit_code == "A12-08"  # type: ignore[union-attr]
    request = parse_request({"contract": "AnalysisRequest@1", "question": "q", "subject_unit_code": "OCP-U00001",
                             "wants": ["explain"], **PIN})
    assert request.subject_unit_code == "OCP-U00001"


def test_two_different_codes_or_word_fragments_are_no_unit() -> None:
    assert classify("So sánh OCP-U00001 với SMC-U00002, vì sao bán chậm", **PIN) is None  # ambiguous: no guess
    assert UNIT_CODE.findall("Ocean Park OCP-U và MAS-U") == []
