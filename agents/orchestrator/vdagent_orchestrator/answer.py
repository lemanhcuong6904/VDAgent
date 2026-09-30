"""The chat answer of a DAG run (WS5): values quoted from the verified artifacts, never computed here.

A failed run starts with "Không hoàn thành" and names the failing step and error code; a partial run says what is
missing. Every figure comes from a comparison / insight artifact returned by a completed step and every artifact is
cited by id. The peer set is flagged with B-11 (no approved rule for the seven golden peers).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .dag import Plan
from .executor import RunOutcome

STATUS_VI = {"completed": "hoàn tất", "partial": "hoàn tất một phần", "failed": "thất bại", "skipped": "bỏ qua",
             "timed_out": "quá hạn", "pending": "chưa chạy", "running": "đang chạy"}
UNITS_VI = {"days": "ngày", "VND/m2": "VND/m²"}


def vn_number(value: Any, places: int | None = None) -> str:
    """Vietnamese formatting of an exact value: 72500000 → 72.500.000; places=2: "12.4" → 12,40."""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    if places is not None:
        d = d.quantize(Decimal(1).scaleb(-places))
    sign = "-" if d < 0 else ""
    whole, _, frac = f"{abs(d):f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return sign + grouped + ("," + frac if frac else "")


async def _payload(tools: Any, ref: dict[str, Any]) -> dict[str, Any]:
    env = await tools.call("artifact_get", {"artifact_id": ref["artifact_id"], "version": ref["version"]})
    return env["payload"]


async def compose_answer(plan: Plan, outcome: RunOutcome, tools: Any) -> str:
    steps = outcome.steps
    refs = {r["artifact_type"]: r for s in steps.values() if s.status == "completed" for r in s.output_refs}
    lines: list[str] = []
    subject = plan.steps[0].spec.get("subject_unit_code", "")
    if outcome.status == "failed":
        bad = next((s for s in steps.values() if s.status in ("failed", "timed_out")), None) or next(iter(steps.values()))
        code = (bad.error or {}).get("code", bad.status)
        lines.append(f"Không hoàn thành phân tích căn {subject}: bước {bad.step_id} ({bad.agent}) {STATUS_VI.get(bad.status, bad.status)}"
                     f" — {code}: {(bad.error or {}).get('message', '')}".rstrip(": "))
    else:
        note = "" if outcome.status == "completed" else " (một phần — xem hạn chế bên dưới)"
        lines.append(f"Phân tích căn {subject} @ {plan.snapshot_id} / {plan.semantic_config_version}{note}.")

    if "comparison" in refs:
        comparison = await _payload(tools, refs["comparison"])
        for m in comparison.get("metrics", []):
            bench = m.get("benchmark") or {}
            if m.get("subjectValue") is None or bench.get("value") is None:
                continue
            unit = UNITS_VI.get(m.get("unit"), m.get("unit") or "")
            gap = f" (chênh {vn_number(m['pctGap'], 2)}%)" if m.get("pctGap") is not None else ""
            lines.append(f"- {m['metric']}: {vn_number(m['subjectValue'])} {unit} so với trung vị {vn_number(bench['value'])} {unit}"
                         f" của {bench.get('n')} căn tương đồng{gap} [{refs['comparison']['artifact_id']}]")
        if "peer_definition" in refs:
            peers = (await _payload(tools, refs["peer_definition"])).get("peers") or []
            codes = ", ".join(p.get("entityCode", "?") for p in peers)
            lines.append(f"- Nhóm tương đồng theo luật hiện hành của Compare: {len(peers)} căn ({codes})"
                         f" [{refs['peer_definition']['artifact_id']}]. Tập 7 căn golden chưa có luật được duyệt (B-11).")
    if "insight" in refs:
        insight = await _payload(tools, refs["insight"])
        for item in (insight.get("insight") or {}).get("insights", [])[:3]:
            text = (item.get("claim") or {}).get("rendered_text")
            if text:
                cause = f"{item['cause_code']}: " if item.get("cause_code") else ""
                lines.append(f"- {cause}{text} [{refs['insight']['artifact_id']}]")
    charts = [r for s in steps.values() if s.agent == "chart" and s.status == "completed" for r in s.output_refs]
    chart_steps = [s for s in steps.values() if s.agent == "chart"]
    if charts:
        lines.append(f"- Biểu đồ: {', '.join(r['artifact_id'] for r in charts)}")
    elif chart_steps:
        s = chart_steps[0]
        lines.append(f"- Biểu đồ: không tạo được ({STATUS_VI.get(s.status, s.status)}: {(s.error or {}).get('code', '')}).")
    report_steps = [s for s in steps.values() if s.agent == "report"]
    if report_steps:
        report_step = report_steps[0]
        report_refs = [r for r in report_step.output_refs if r["artifact_type"] == "report"]
        if report_refs:
            lines.append(f"- Báo cáo đã lưu: {', '.join(r['artifact_id'] for r in report_refs)}")
        elif report_step.status != "skipped":
            lines.append(f"- Báo cáo: không tạo được ({STATUS_VI.get(report_step.status, report_step.status)}: "
                         f"{(report_step.error or {}).get('code', '')}).")

    lines.append("")
    lines.append("| Bước | Agent | Trạng thái | Artifact |")
    lines.append("|---|---|---|---|")
    for s in steps.values():
        ids = ", ".join(r["artifact_id"] for r in s.output_refs) or ((s.error or {}).get("code") or "—")
        lines.append(f"| {s.step_id} | {s.agent}.{s.operation} | {STATUS_VI.get(s.status, s.status)}{' (dùng lại)' if s.reused else ''} | {ids} |")
    limits = sorted({lim for s in steps.values() for lim in s.limitations})
    if limits:
        lines.append("")
        lines.append("Hạn chế: " + ", ".join(limits))
    lines.append(f"\nrun_state: {outcome.run_state_id} · plan {plan.plan_id}")
    return "\n".join(lines)


async def run_and_answer(ctx: Any, tools: Any, plan: Plan, **executor_kw: Any) -> RunOutcome:
    """Execute the plan and emit the final chat answer (a step without tool calls ends the turn)."""
    from .executor import DagExecutor

    outcome = await DagExecutor(ctx, tools, **executor_kw).run(plan)
    report_outcome(ctx, outcome.status)
    await ctx.emit_assistant(await compose_answer(plan, outcome, tools))
    return outcome


def report_outcome(ctx: Any, status: str) -> None:
    """Tell the Backend the run's business outcome (WS7 F-03): a failed run must not look like a success.

    `ctx.report_outcome` is optional in the SDK; a ctx without it (older Backend) is left untouched.
    """
    report = getattr(ctx, "report_outcome", None)
    if callable(report):
        report({"completed": "completed", "partial": "partial"}.get(status, "failed"))
