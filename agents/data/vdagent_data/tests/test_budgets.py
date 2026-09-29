from __future__ import annotations

import time

import pytest

from vdagent_agentkit.llm import LlmError, LlmErrorCode
from vdagent_data.budgets import Budget, BudgetExceeded
from vdagent_data.errors import failure_from
from vdagent_data.operations import OperationError


def test_12_llm_calls_budget_exceeded() -> None:
    budget = Budget()
    for _ in range(12):
        budget.spend_llm()
    with pytest.raises(BudgetExceeded) as exc:
        budget.spend_llm()
    assert exc.value.what == "llm"


def test_20_sql_runs_budget_exceeded() -> None:
    budget = Budget()
    budget.spend_sql(20)
    with pytest.raises(BudgetExceeded):
        budget.spend_sql()


def test_90s_budget_exceeded() -> None:
    budget = Budget(started=time.monotonic() - 91)
    with pytest.raises(BudgetExceeded) as exc:
        budget.spend_sql()
    assert exc.value.what == "time"


def test_budget_exceeded_maps_to_code() -> None:
    failure = failure_from(BudgetExceeded("sql", 20))
    assert failure.code == "BUDGET_EXCEEDED" and "sql" in failure.reason


def test_llm_unavailable_code() -> None:
    assert failure_from(LlmError(LlmErrorCode.UNAVAILABLE, "503")).code == "LLM_UNAVAILABLE"
    assert failure_from(LlmError(LlmErrorCode.INVALID_OUTPUT, "bad json")).code == "LLM_UNAVAILABLE"


def test_llm_quota_exhausted_code() -> None:
    assert failure_from(LlmError(LlmErrorCode.QUOTA_EXHAUSTED, "quota")).code == "LLM_QUOTA_EXHAUSTED"


def test_other_exceptions() -> None:
    assert failure_from(OperationError("ENTITY_NOT_FOUND", "x")).code == "ENTITY_NOT_FOUND"
    assert failure_from(LookupError("package art_1 not found")).code == "SPEC_MISMATCH"
    internal = failure_from(ZeroDivisionError("boom"))
    assert internal.code == "INTERNAL_ERROR" and "boom" not in internal.reason  # no stack detail to users
