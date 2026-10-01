"""The chat answer of a DAG run (WS5): values quoted from the verified artifacts, never computed here.

A failed run starts with "Không hoàn thành" and names the failing step and error code; a partial run says what is
missing. Every figure comes from a comparison / insight artifact returned by a completed step and every artifact is
cited by id. The peer set is flagged with B-11 (no business-approved peer rule yet).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from vdagent_contracts.insight_evidence import METRICS, peer_bindings, peer_claims

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


async def _envelope(tools: Any, ref: dict[str, Any]) -> dict[str, Any]:
    return await tools.call("artifact_get", {"artifact_id": ref["artifact_id"], "version": ref["version"]})


def insight_lines(insight: dict[str, Any], comparison: dict[str, Any] | None, limit: int = 3) -> tuple[list[str], list[str]]:
    """The answer's Insight lines: peer facts only from Compare (bound by metric id through insight_evidence@2);
    a sentence carrying its own peer number (stale/malformed artifact) is withheld and reported."""
    stale: dict[str, list[str]] = {}
    for insight_id, slot, value in peer_claims(insight["payload"]):
        stale.setdefault(insight_id, []).append(f"PEER_BASIS_DIFFERS:{insight_id}:{slot}={value}")
    bindings = peer_bindings(insight, comparison)
    lines: list[str] = []
    for item in (insight["payload"].get("insight") or {}).get("insights", [])[:limit]:
        text = (item.get("claim") or {}).get("rendered_text")
        cause = f"{item['cause_code']}: " if item.get("cause_code") else ""
        if item.get("insight_id") in stale:
            lines.append(f"- {cause}(câu diễn giải nêu số liệu nhóm tương đồng không phải của Compare — không hiển thị) [{insight['artifact_id']}]")
            continue
        if not text:
            continue
        peer = ""
        for b in bindings.get(item.get("insight_id") or "", []):
            fact = b.fact
            if fact is None or fact.delta_pct is None:
                peer += " Mức chênh so với nhóm tương đồng cần bước so sánh (Compare); lần chạy này không có kết quả đó."
                continue
            name = METRICS[fact.metric_id].label if fact.metric_id in METRICS else fact.metric
            peer += (f" So với nhóm tương đồng của Compare ({fact.peer_count} căn): {name} chênh {vn_number(fact.delta_pct, 2)}%"
                     f" [{fact.comparison_id.split('@')[0]}].")
        lines.append(f"- {cause}{text}{peer} [{insight['artifact_id']}]")
    return lines, sorted({c for codes in stale.values() for c in codes})


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
                         f" [{refs['peer_definition']['artifact_id']}]. Luật chọn nhóm tương đồng chưa được nghiệp vụ duyệt (B-11).")
    peer_codes: list[str] = []
    if "insight" in refs:
        comparison = await _envelope(tools, refs["comparison"]) if "comparison" in refs else None
        insight_text, peer_codes = insight_lines(await _envelope(tools, refs["insight"]), comparison)
        lines += insight_text
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
    limits = sorted({lim for s in steps.values() for lim in s.limitations} | set(peer_codes))
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
