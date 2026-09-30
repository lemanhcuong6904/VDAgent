import pytest
from pydantic import ValidationError

from vdagent_contracts.catalog import AgentCatalog
from vdagent_contracts.catalogs.stubs import STUB_CATALOGS
from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import AGENT_GROUP, AgentGroup, TaskKind, served_task_kinds
from vdagent_contracts.scope import AuthorizedScope, UserContext


def _catalog(**op_overrides: object) -> AgentCatalog:
    op: dict[str, object] = {
        "operation": "aggregate_metrics",
        "description": "Tính metric theo nhóm",
        "requires": [],
        "produces": ["metric_table", "dq_report"],
        "outputs": ["CHAT_ANSWER"],
        "serves": ["LOOKUP"],
        "deadline_s": 90,
        "error_codes": {"AMBIGUOUS_REQUEST": "NEED_INPUT", "DQ_BLOCKING": "DATA_QUALITY"},
    }
    op.update(op_overrides)
    return AgentCatalog.model_validate(
        {"agent": "data", "contract_version": "1.0.0", "catalog_version": "sc-1", "operations": [op]}
    )


def test_ten_error_classes() -> None:
    assert len(ErrorClass) == 10
    assert ErrorClass("WRONG_RESULT") is ErrorClass.WRONG_RESULT


def test_unknown_code_classifies_fatal() -> None:
    catalog = _catalog()
    assert catalog.classify("AMBIGUOUS_REQUEST") is ErrorClass.NEED_INPUT
    assert catalog.classify("DQ_BLOCKING", operation="aggregate_metrics") is ErrorClass.DATA_QUALITY
    assert catalog.classify("SOMETHING_NEW") is ErrorClass.FATAL


def test_catalog_operation_requires_produces_serves() -> None:
    catalog = _catalog(requires=["unit_set"], uses_if_present=["comparison"])
    op = catalog.operation("aggregate_metrics")
    assert op.requires == ["unit_set"] and op.uses_if_present == ["comparison"]
    assert op.serves == [TaskKind.LOOKUP]
    with pytest.raises(KeyError):
        catalog.operation("nope")
    with pytest.raises(ValidationError):
        _catalog(deadline_s=0)
    with pytest.raises(ValidationError):
        _catalog(error_codes={"X": "NOT_A_CLASS"})


def test_stub_catalogs_compare_chart_report_valid() -> None:
    assert set(STUB_CATALOGS) == {"compare", "chart", "report"}
    compare = STUB_CATALOGS["compare"].operation("compare_to_peers")
    assert compare.requires == ["peer_candidates"] and compare.serves == [TaskKind.COMPARE]
    assert STUB_CATALOGS["report"].operation("draft_report").outputs == ["REPORT"]
    assert all(c.fixture for c in STUB_CATALOGS.values())
    assert AGENT_GROUP["report"] is AgentGroup.OUTPUT


def test_served_kind_table_int8() -> None:
    data = _catalog(serves=[])
    assert served_task_kinds([data]) == {TaskKind.LOOKUP}  # INT-8 fallback for aggregate_metrics
    assert TaskKind.COMPARE in served_task_kinds([data, STUB_CATALOGS["compare"]])
    assert TaskKind.TREND not in served_task_kinds([data, *STUB_CATALOGS.values()])


def test_user_context_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        UserContext.model_validate({"user_id": "u", "signature": "x"})
    assert UserContext(user_id="u").role == "SALES_OPS"


def test_scope_contract_contains_checks_project_and_zone() -> None:
    scope = AuthorizedScope(project_ids=["PRJ-X"], zone_ids=["Z-AQ1"])
    assert scope.contains(project_id="PRJ-X")
    assert scope.contains(project_id="PRJ-X", zone_id="Z-ANY")
    assert scope.contains(project_id="PRJ-Y", zone_id="Z-AQ1")
    assert not scope.contains(project_id="PRJ-Y")
    assert not scope.contains(project_id="PRJ-Y", zone_id="Z-OTHER")
