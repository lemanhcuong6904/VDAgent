"""Exceptions → Data catalog error codes (build spec 02 §3). Codes not in the catalog are never produced."""

from __future__ import annotations

import logging

from vdagent_agentkit.llm import LlmError, LlmErrorCode
from vdagent_data.budgets import BudgetExceeded
from vdagent_data.operations import OperationError
from vdagent_data.pipeline.s0_intake import Failure

log = logging.getLogger(__name__)


def failure_from(exc: BaseException) -> Failure:
    if isinstance(exc, BudgetExceeded):
        return Failure("BUDGET_EXCEEDED", f"Vượt ngân sách của bước ({exc.what}).")
    if isinstance(exc, LlmError):
        code = "LLM_QUOTA_EXHAUSTED" if exc.code is LlmErrorCode.QUOTA_EXHAUSTED else "LLM_UNAVAILABLE"
        return Failure(code, "Dịch vụ mô hình ngôn ngữ không dùng được lúc này.")
    if isinstance(exc, OperationError):
        return Failure(exc.code, exc.reason)
    if isinstance(exc, LookupError):
        return Failure("SPEC_MISMATCH", f"Đầu vào của bước không dùng được: {exc}")
    log.exception("data agent internal error", exc_info=exc)
    return Failure("INTERNAL_ERROR", "Lỗi nội bộ của Data Agent; đội vận hành đã được báo.")
