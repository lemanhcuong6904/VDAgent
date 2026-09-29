"""Closing the run (build spec 01 §12 FIN-2…5; source §9 Failure Matrix) and the Vietnamese summary (no LLM).

FIN-3: a Data step not completed, or DATA_QUALITY → failed; an analytical step not completed → partial; only output
steps missing → completed with "thiếu báo cáo"; a run with only output steps that fail → failed. Replaced and dropped
steps are not failures. FIN-4: analysis coverage = completed analytical ÷ analytical steps of the current plan.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.intents import AGENT_GROUP, AgentGroup, OutputKind, TaskKind
from vdagent_orchestrator.catalogs import CatalogRegistry
from vdagent_orchestrator.intent import IntentFrame
from vdagent_orchestrator.records import RunRecord, StepRecord
from vdagent_orchestrator.wording import no_data_sentence, part, part_lower, timeout_sentence

STATUS_VI = {"completed": "Hoàn tất", "partial": "Hoàn tất một phần", "failed": "Không thành công",
             "canceled": "Đã hủy", "rejected": "Không thực hiện"}
REASON_VI = {"OK": "", "DATA_STEP_FAILED": "Không lấy được số liệu nên dừng phân tích.",
             "DATA_QUALITY": "Dữ liệu chưa đạt kiểm tra chất lượng; đội dữ liệu đã được báo.",
             "ANALYTICAL_MISSING": "Một số phần phân tích chưa dùng được; các phần còn lại vẫn hiển thị.",
             "REPORT_MISSING": "Thiếu báo cáo nháp; bạn có thể yêu cầu tạo lại báo cáo sau.",
             "OUTPUT_FAILED": "Không tạo được báo cáo.",
             "LLM_UNAVAILABLE": ("Hệ thống tạm thời không xử lý được câu hỏi này; câu hỏi tra một chỉ số (vd \"DOM trung bình của Aqua 1 là bao nhiêu?\") vẫn được trả lời."),
             "NO_USER_CONTEXT": "Không xác định được phạm vi dữ liệu bạn được xem; hãy thử lại sau.",
             "LLM_QUOTA_EXHAUSTED": "Hệ thống tạm thời không lập được kế hoạch.",
             "PLAN_REJECTED": "Hệ thống không lập được kế hoạch hợp lệ cho câu hỏi này."}
COVERAGE_Q = Decimal("0.001")


class MissingPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: str
    agent: str
    status: str
    root_step_id: str
    error_code: str | None
    error_class: str | None
    technical_reason: str
    message_vi: str


class PackageRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: str
    agent: str
    package_id: str
    summary: str


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str
    reason: str
    missing_parts: list[MissingPart] = Field(default_factory=list)
    missing_outputs: list[OutputKind] = Field(default_factory=list)
    dropped_parts: list[dict[str, str]] = Field(default_factory=list)
    uncovered_task_kinds: list[TaskKind] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    sales_ops_inputs: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limited_mode: bool = False
    snapshot_id: str | None = None
    plan_version: int = 0
    replan_count: int = 0
    analysis_coverage: Decimal | None = None
    data_confidence: str | None = None
    packages: list[PackageRef] = Field(default_factory=list)


def live_steps(run: RunRecord) -> list[StepRecord]:
    """The current plan: replaced and dropped steps are left out."""
    replaced = {s.replaces for s in run.steps.values() if s.replaces}
    return [s for s in run.ordered() if s.step_id not in replaced and "dropped" not in s.flags]


def close_status(run: RunRecord) -> tuple[str, str]:
    live = live_steps(run)
    if any(s.error_class is ErrorClass.DATA_QUALITY for s in live):
        return "failed", "DATA_QUALITY"
    if any(s.agent == "data" and s.status != "completed" for s in live):
        return "failed", "DATA_STEP_FAILED"
    if any(AGENT_GROUP.get(s.agent) is AgentGroup.ANALYTICAL and s.status != "completed" for s in live):
        return "partial", "ANALYTICAL_MISSING"
    if live and all(AGENT_GROUP.get(s.agent) is AgentGroup.OUTPUT for s in live) and any(s.status != "completed" for s in live):
        return "failed", "OUTPUT_FAILED"
    if any(s.status != "completed" for s in live):
        return "completed", "REPORT_MISSING"
    return "completed", "OK"


def _root(run: RunRecord, step: StepRecord) -> StepRecord:
    """Walk a skipped step back along its HARD waits to the first step that failed."""
    seen: set[str] = set()
    current = step
    while current.status == "skipped" and current.step_id not in seen:
        seen.add(current.step_id)
        upstream = [run.steps[w.step_id] for w in current.waits if w.mode == "HARD" and w.step_id in run.steps
                    and run.steps[w.step_id].status != "completed"]
        if not upstream:
            break
        current = upstream[0]
    return current


def _message(root: StepRecord, missing: StepRecord, mention: str, needs: list[str]) -> str:
    if root.error_code == "TIMEOUT":
        return timeout_sentence(root.agent)
    if root.error_class is ErrorClass.NO_DATA:
        need = ", ".join(needs) if needs and root.agent == "data" else part_lower(missing.agent)
        return no_data_sentence(need, mention)
    if root.error_class is ErrorClass.NO_ACCESS:
        return f"Phần {part_lower(missing.agent)} chưa dùng được vì nằm ngoài phạm vi dữ liệu bạn được xem."
    if root is missing:
        return f"Phần {part_lower(missing.agent)} chưa dùng được; các phần khác vẫn hiển thị."
    return f"Phần {part_lower(missing.agent)} chưa có vì phần {part_lower(root.agent)} chưa dùng được."


def summarize(run: RunRecord, registry: CatalogRegistry | None = None) -> RunSummary:
    registry = registry or CatalogRegistry.load()
    status, reason = close_status(run)
    live = live_steps(run)
    mention = run.frame.mentions[0].text if run.frame.mentions else "phạm vi bạn hỏi"
    needs = run.frame.unmatched_needs or run.frame.metrics
    missing = []
    for step in live:
        if step.status == "completed":
            continue
        root = _root(run, step)
        missing.append(MissingPart(
            step_id=step.step_id, agent=step.agent, status=step.status, root_step_id=root.step_id,
            error_code=root.error_code, error_class=root.error_class.value if root.error_class else None,
            technical_reason=root.error_message or "", message_vi=_message(root, step, mention, needs)))
    produced: set[OutputKind] = set()
    for step in live:
        if step.status == "completed":
            try:
                produced |= set(registry.operation(step.agent, step.operation).outputs)
            except KeyError:
                pass
    analytical = [s for s in live if AGENT_GROUP.get(s.agent) is AgentGroup.ANALYTICAL]
    coverage = (Decimal(sum(s.status == "completed" for s in analytical)) / Decimal(len(analytical))).quantize(
        COVERAGE_Q, rounding=ROUND_HALF_UP) if analytical else None
    confidence = next((s.data_confidence for s in live if s.agent == "data" and s.data_confidence), None)
    return RunSummary(
        status=status, reason=reason, missing_parts=missing,
        missing_outputs=[o for o in run.frame.requested_outputs if o not in produced],
        dropped_parts=[{"step_id": s.step_id, "agent": s.agent, "operation": s.operation}
                       for s in run.ordered() if "dropped" in s.flags and s.step_id not in {x.replaces for x in run.steps.values()}],
        uncovered_task_kinds=list(run.frame.uncovered_task_kinds), warnings=list(run.warnings),
        sales_ops_inputs=list(run.sales_ops_inputs), assumptions=list(run.frame.assumptions),
        limited_mode=run.plan.limited_mode, snapshot_id=run.snapshot_id, plan_version=run.plan.version,
        replan_count=run.replan_count, analysis_coverage=coverage, data_confidence=confidence,
        packages=[PackageRef(step_id=s.step_id, agent=s.agent, package_id=s.refs[0].artifact_id, summary=s.summary)
                  for s in live if s.status == "completed" and s.refs])


def plan_failed_summary(frame: IntentFrame, reason: str) -> RunSummary:
    """PLAN failed and no fallback plan → failed (Failure Matrix, last row)."""
    return RunSummary(status="failed", reason=reason, uncovered_task_kinds=list(frame.uncovered_task_kinds),
                      assumptions=list(frame.assumptions))


def failure_text(reason: str) -> str:
    """A run that never started (no understanding, no user context)."""
    return f"**Kết quả:** {STATUS_VI['failed']}\n{REASON_VI.get(reason, reason)}"


def render_markdown(summary: RunSummary) -> str:
    lines = [f"**Kết quả:** {STATUS_VI.get(summary.status, summary.status)}"]
    if REASON_VI.get(summary.reason):
        lines.append(REASON_VI[summary.reason])
    for package in summary.packages:
        lines += ["", f"**{part(package.agent)}**", package.summary]
    if summary.missing_parts:
        lines += ["", "**Phần thiếu:**", *(f"- {part(p.agent)}: {p.message_vi}" for p in summary.missing_parts)]
    if summary.uncovered_task_kinds:
        lines += ["", "**Chưa làm được:** hệ thống chưa có chức năng cho một phần câu hỏi."]
    if summary.assumptions:
        lines += ["", "**Giả định:**", *(f"- {a}" for a in summary.assumptions)]
    if summary.warnings:
        lines += ["", "**Lưu ý:** một số kết quả có cảnh báo về độ tin cậy hoặc cỡ mẫu."]
    technical = [f"- snapshot: {summary.snapshot_id or '-'} · kế hoạch v{summary.plan_version} · lên lại kế hoạch "
                 f"{summary.replan_count} lần · coverage {summary.analysis_coverage if summary.analysis_coverage is not None else '-'}"
                 f" · data confidence {summary.data_confidence or '-'}"]
    technical += [f"- {p.step_id} ({p.agent}, {p.status}) ← {p.root_step_id}: {p.error_code} / {p.error_class} — {p.technical_reason}"
                  for p in summary.missing_parts]
    technical += [f"- cảnh báo {w['step_id']}: {w['code']}" for w in summary.warnings]
    lines += ["", "<details><summary>Chi tiết kỹ thuật</summary>", "", *technical, "", "</details>"]
    return "\n".join(lines)


__all__ = ["MissingPart", "PackageRef", "RunSummary", "close_status", "failure_text", "live_steps", "plan_failed_summary",
           "render_markdown", "summarize"]
