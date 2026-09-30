"""FIXTURE — not a contract. Stub catalogs for agents without a spec yet (build spec 00 §4.3, DEC-020)."""

from __future__ import annotations

from vdagent_contracts.catalog import AgentCatalog

_COMMON_ERRORS = {"LLM_UNAVAILABLE": "TRANSIENT", "LLM_QUOTA_EXHAUSTED": "QUOTA_EXHAUSTED", "INTERNAL_ERROR": "FATAL"}


def _stub(agent: str, operation: str, description: str, **fields: object) -> AgentCatalog:
    return AgentCatalog.model_validate(
        {
            "agent": agent,
            "contract_version": "0.0.0-stub",
            "catalog_version": "stub-1",
            "fixture": True,
            "operations": [
                {"operation": operation, "description": description, "deadline_s": 120,
                 "error_codes": {**_COMMON_ERRORS, "WRONG_RESULT": "WRONG_RESULT", "NO_DATA": "NO_DATA"}, **fields}
            ],
        }
    )


STUB_CATALOGS: dict[str, AgentCatalog] = {
    "compare": _stub(
        "compare", "compare_to_peers", "So sánh căn mục tiêu với nhóm căn tương đồng",
        requires=["peer_candidates"], uses_if_present=["metric_table"], produces=["comparison"],
        outputs=["CHAT_ANSWER"], serves=["COMPARE"],
    ),
    "chart": _stub(
        "chart", "draw_chart", "Vẽ biểu đồ từ bảng metric và kết quả phân tích",
        requires=["metric_table"], uses_if_present=["insight", "comparison"], produces=["chart"], outputs=["CHART"],
    ),
    "report": _stub(
        "report", "draft_report", "Soạn báo cáo nháp từ số liệu, phân tích và biểu đồ",
        requires=["metric_table"], uses_if_present=["insight", "comparison", "chart"], produces=["report_draft"],
        outputs=["REPORT"],
    ),
}
