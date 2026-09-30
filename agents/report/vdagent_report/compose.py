"""Deterministic report composition and evidence validation (WS6, offline Report Mode).

`compose_report` writes the six required sections only from the resolved upstream artifacts. Every number it prints
is a `Statement` (`S<n>` in the text) carrying the exact upstream value and its `source_ref`
(`<artifact_id>@<version>#<json pointer>`); nothing is computed or estimated here, wording stays associative
("có khả năng liên quan"), and unavailable metrics / open business decisions are listed in section 6.

`validate_statements` and `validate_chart` re-resolve every statement and every chart binding against the artifacts
themselves; any mismatch, missing source or malformed chart makes the report invalid (it is then not persisted).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from vdagent_contracts.step_inputs import AnalysisInputs
from vdagent_contracts.vega_lite import validate_vega_lite

SECTION_IDS = ("context", "executive_summary", "key_metrics", "analysis", "evidence", "limitations")
SECTION_TITLES = ("1. Bối cảnh", "2. Tóm tắt điều hành", "3. Chỉ số chính", "4. Phân tích & Insight",
                  "5. Bằng chứng & Trực quan hóa", "6. Hạn chế & Chất lượng dữ liệu")
METRIC_VI = {"dom": ("DOM", "ngày"), "net_asking_price_per_m2": ("Giá ròng/m²", "VND/m²")}
CHART_KEYS = ("chart_type", "vega_lite", "dataset", "bindings")
VEGA_SCHEMA_PREFIX = "https://vega.github.io/schema/vega-lite/"
LIMITATION_VI = {
    "METRIC_UNAVAILABLE": "chỉ số không có nguồn trong DW hoặc bị trống (giữ null, không thay bằng 0)",
    "WINDOW_INCOMPLETE": "cửa sổ dữ liệu không đủ ngày (giữ null)",
    "DQ_MISSING": "một số dòng thiếu giá trị",
    "SYNTHETIC_SOURCE": "giá trị trong fixture là tổng hợp (B-3)",
    "CONFIG_PENDING": "tham số cấu hình semantic còn PENDING",
    "BLOCKED": "quyết định nghiệp vụ chưa được duyệt",
    "UPSTREAM_MISSING": "thiếu artifact đầu vào; phần tương ứng bị lược bỏ",
    "UPSTREAM_FAILED": "bước trước thất bại; phần tương ứng bị lược bỏ",
    "FIELD_UNAVAILABLE": "trường dữ liệu không có trong DW",
    "NOT_CHARTED_NULL": "giá trị null nên không được vẽ",
    "INVALID_BINDING": "binding không phải số nên bị loại",
}
Lookup = Callable[[str], Any]


@dataclass(frozen=True)
class Statement:
    section: str
    text: str
    value_exact: str
    source_ref: str | None
    statement_id: str = ""


@dataclass
class ReportDoc:
    title: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    actions: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    @property
    def markdown(self) -> str:
        parts = [f"# {self.title}"]
        for s in self.sections:
            parts.append(f"## {s['title']}\n\n{s['markdown']}")
        return "\n\n".join(parts)

    def to_payload(self) -> dict[str, Any]:
        return {"title": self.title, "sections": self.sections, "markdown": self.markdown,
                "statements": [asdict(s) for s in self.statements], "charts": self.charts, "tables": self.tables,
                "actions": self.actions}


def vn_number(value: Any, places: int | None = None) -> str:
    d = Decimal(str(value))
    if places is not None:
        d = d.quantize(Decimal(1).scaleb(-places))
    whole, _, frac = f"{abs(d):f}".partition(".")
    return ("-" if d < 0 else "") + f"{int(whole):,}".replace(",", ".") + ("," + frac if frac else "")


def _label(env: dict[str, Any]) -> str:
    return f"{env['artifact_id']}@{env['version']}"


class _Writer:
    def __init__(self) -> None:
        self.statements: list[Statement] = []

    def num(self, section: str, value: Any, source_ref: str, *, places: int | None = None, text: str = "") -> str:
        """Register an exact upstream value and return its display with the statement marker."""
        sid = f"S{len(self.statements) + 1}"
        self.statements.append(Statement(section, text, str(value), source_ref, sid))
        return f"{vn_number(value, places)} [{sid}]"


def compose_report(inputs: AnalysisInputs, question: str, snapshot_id: str, semantic: str, title: str | None = None) -> ReportDoc:
    w = _Writer()
    cmp, pd, ins = inputs.comparison, inputs.peer_definition, inputs.insight
    subject = ((cmp or {}).get("payload", {}).get("subject") or {}).get("entityCode")
    if subject is None and ins is not None:
        items = ins["payload"]["insight"].get("insights") or []
        subject = next(((i.get("subject") or {}).get("label") for i in items if i.get("subject")), None)
    subject = subject or "?"
    limitations = sorted(set(inputs.limitations) | {f"UPSTREAM_MISSING:{m}" for m in inputs.missing}
                         | ({"UPSTREAM_MISSING:chart_spec"} if not inputs.charts else set()))
    doc = ReportDoc(title=title or f"Báo cáo căn {subject} @ {snapshot_id}", limitations=limitations)
    body: dict[str, list[str]] = {k: [] for k in SECTION_IDS}

    # 1. context
    sources = [f"`{_label(e)}` ({e['artifact_type']})" for e in (ins, pd, cmp, *inputs.charts) if e is not None]
    body["context"] += [f"- Câu hỏi: {question}", f"- Đối tượng: căn {subject}; dữ liệu `{snapshot_id}` / semantic `{semantic}`;"
                        f" phạm vi được phép: {', '.join(inputs.authorized_project_ids) or '—'}.",
                        f"- Dataset gốc: `{inputs.dataset_ref.artifact_id}@{inputs.dataset_ref.version}`; đầu vào: {', '.join(sources)}."]

    # 2 + 3. comparison metrics
    metric_rows: list[str] = []
    if cmp is not None:
        cid = _label(cmp)
        for i, m in enumerate(cmp["payload"].get("metrics") or []):
            bench = m.get("benchmark") or {}
            if m.get("subjectValue") is None or bench.get("value") is None:
                continue
            name, unit = METRIC_VI.get(m["metric"], (m["metric"], m.get("unit") or ""))
            base = f"{cid}#/metrics/{i}"
            subject_v = w.num("key_metrics", m["subjectValue"], f"{base}/subjectValue", text=f"{name} của {subject}")
            bench_v = w.num("key_metrics", bench["value"], f"{base}/benchmark/value", text=f"trung vị {name}")
            n_v = w.num("key_metrics", bench["n"], f"{base}/benchmark/n", text="số căn tương đồng") if bench.get("n") is not None else "—"
            gap_v = w.num("key_metrics", m["pctGap"], f"{base}/pctGap", places=2, text="chênh %") if m.get("pctGap") is not None else "—"
            metric_rows.append(f"| {name} ({unit}) | {subject_v} | {bench_v} | {n_v} | {gap_v}% |")
            summary_subject = w.num("executive_summary", m["subjectValue"], f"{base}/subjectValue")
            summary_bench = w.num("executive_summary", bench["value"], f"{base}/benchmark/value")
            gap = f" (chênh {w.num('executive_summary', m['pctGap'], f'{base}/pctGap', places=2)}%)" if m.get("pctGap") is not None else ""
            body["executive_summary"].append(f"- {name}: {summary_subject} {unit} so với trung vị nhóm tương đồng {summary_bench} {unit}{gap}.")
        if metric_rows:
            body["key_metrics"] += ["| Chỉ số | Căn | Trung vị nhóm | Số căn | Chênh |", "|---|---|---|---|---|", *metric_rows]
            doc.tables.append({"table_id": "key_metrics", "source": cid})
    else:
        body["key_metrics"].append("Không có artifact so sánh (comparison) nên không có bảng chỉ số so với nhóm tương đồng.")

    # 4. analysis (insight) + actions
    actions: list[dict[str, Any]] = []
    if ins is not None:
        iid = _label(ins)
        items = ins["payload"]["insight"].get("insights") or []
        for ii, item in enumerate(items):
            claim = item.get("claim") or {}
            values = [w.num("analysis", b["value"], f"{iid}#/insight/insights/{ii}/claim/numeric_bindings/{bi}/value", text=b.get("slot", ""))
                      for bi, b in enumerate(claim.get("numeric_bindings") or []) if _is_number(b.get("value"))]
            cause = f"**{item['cause_code']}** — " if item.get("cause_code") else ""
            evidence = f" (số liệu: {', '.join(values)})" if values else ""
            body["analysis"].append(f"- {cause}{claim.get('rendered_text', '')}{evidence} `[{iid}]`")
            rec = item.get("recommendation")
            if rec and rec.get("text"):
                actions.append({"action_code": rec.get("action_code"), "text": rec["text"],
                                "source_ref": f"{iid}#/insight/insights/{ii}/recommendation/text"})
        if items and any(i.get("cause_code") for i in items):
            body["executive_summary"].append("- Yếu tố có khả năng liên quan (theo Insight): "
                                             + ", ".join(sorted({i["cause_code"] for i in items if i.get("cause_code")}))
                                             + ". Đây là mối liên hệ quan sát được, không phải kết luận nhân quả.")
    else:
        body["analysis"].append("Không có artifact insight nên không có phần diễn giải yếu tố liên quan.")
    if pd is not None:
        peers = pd["payload"].get("peers") or []
        body["analysis"].append(f"- Nhóm tương đồng theo luật hiện hành của Compare `[{_label(pd)}]`: "
                                + ", ".join(p.get("entityCode", "?") for p in peers)
                                + ". Tập 7 căn golden chưa có luật được duyệt (B-11), nên nhóm này chỉ mang tính mô tả.")
    body["analysis"].append("\n**Đề xuất hành động (từ Insight, cần phê duyệt):**")
    for a in actions:
        body["analysis"].append(f"- {a['text']} (`{a['action_code']}`, nguồn `{a['source_ref']}`)")
    note = None
    if len(actions) < 2:
        note = (f"Chỉ có {len(actions)} đề xuất được Insight hỗ trợ bằng bằng chứng; báo cáo không tự thêm đề xuất khác"
                " vì không có dữ liệu chứng minh.")
        body["analysis"].append(f"- {note}")
    doc.actions = {"items": actions, "insufficient_evidence_note": note}

    # 5. evidence: charts + peer table + statement sources
    for chart in inputs.charts:
        p = chart["payload"]
        doc.charts.append({"artifact_id": chart["artifact_id"], "version": chart["version"], "chart_type": p.get("chart_type"),
                           "title": p.get("title")})
        body["evidence"] += [f"**{p.get('title')}** ({p.get('chart_type')})", "", f"{{{{chart_spec:{chart['artifact_id']}@{chart['version']}}}}}", ""]
    if not inputs.charts:
        body["evidence"].append("Không có biểu đồ (chart_spec) trong đầu vào; dùng bảng số liệu bên dưới.")
    if cmp is not None and cmp["payload"].get("peerValues"):
        cid = _label(cmp)
        rows = ["| Căn | Vai trò | DOM (ngày) | Giá ròng/m² (VND) |", "|---|---|---|---|"]
        for j, entry in enumerate(cmp["payload"]["peerValues"]):
            vals = entry.get("values") or {}
            dom = w.num("evidence", vals["dom"], f"{cid}#/peerValues/{j}/values/dom") if vals.get("dom") is not None else "null"
            price = (w.num("evidence", vals["net_asking_price_per_m2"], f"{cid}#/peerValues/{j}/values/net_asking_price_per_m2")
                     if vals.get("net_asking_price_per_m2") is not None else "null")
            rows.append(f"| {entry.get('entityCode')} | {entry.get('role')} | {dom} | {price} |")
        body["evidence"] += ["**Bảng giá trị căn mục tiêu và nhóm tương đồng**", "", *rows]
        doc.tables.append({"table_id": "peer_values", "source": cid})

    # 6. limitations
    body["limitations"].append("Hạn chế được mang từ các artifact đầu vào (mã → ý nghĩa):")
    for code in limitations:
        body["limitations"].append(f"- `{code}` — {LIMITATION_VI.get(code.split(':', 1)[0], 'xem tài liệu tích hợp')}")
    blockers = []
    if cmp is not None or pd is not None:
        blockers += ["B-11: luật chọn 7 căn tương đồng golden chưa được duyệt; báo cáo dùng nhóm do Compare chọn.",
                     "B-2: `min_peer_count` chưa có giá trị được duyệt (Compare dùng mặc định của engine)."]
    if any(c.startswith("BLOCKED:D2b") for c in limitations):
        blockers.append("D2b: chưa có ánh xạ segment; giữ nguyên giá trị DW.")
    if any(c.startswith("SYNTHETIC_SOURCE:net_area_m2") for c in limitations):
        blockers.append("B-3: `net_area_m2` trong fixture là số tổng hợp; ý nghĩa nghiệp vụ chưa xác nhận.")
    if ins is not None:
        blockers.append("B-12: một số ngưỡng sc-1 riêng của Insight còn PENDING.")
    body["limitations"] += ["", "Quyết định nghiệp vụ còn mở:", *(f"- {b}" for b in blockers)]

    body["evidence"] += ["", "**Nguồn số liệu** (mỗi con số [S*] trỏ tới artifact và JSON pointer):",
                         *(f"- {s.statement_id}: `{s.source_ref}`" for s in w.statements)]
    doc.statements = w.statements
    doc.sections = [{"id": k, "title": t, "markdown": "\n".join(body[k]).strip() or "—"} for k, t in zip(SECTION_IDS, SECTION_TITLES, strict=True)]
    return doc


def _is_number(value: Any) -> bool:
    try:
        return value is not None and not isinstance(value, bool) and Decimal(str(value)).is_finite()
    except InvalidOperation:
        return False


def validate_statements(statements: list[Statement], lookup: Lookup) -> list[str]:
    errors = []
    for st in statements:
        if not st.source_ref:
            errors.append(f"{st.statement_id or st.text}: no source_ref")
            continue
        try:
            value = lookup(st.source_ref)
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f"{st.statement_id}: {st.source_ref} does not resolve")
            continue
        if str(value) != st.value_exact:
            errors.append(f"{st.statement_id}: {st.source_ref} is {value!r}, report says {st.value_exact!r}")
    return errors


def validate_chart(chart: dict[str, Any], lookup: Lookup) -> tuple[int, list[str]]:
    payload, label = chart.get("payload") or {}, _label(chart)
    errors = [f"{label}: missing {k}" for k in CHART_KEYS if k not in payload]
    if not str((payload.get("vega_lite") or {}).get("$schema", "")).startswith(VEGA_SCHEMA_PREFIX):
        errors.append(f"{label}: vega_lite has no Vega-Lite $schema")
    else:  # WS7 F-01: the whole spec must be renderable, not only its $schema
        errors += [f"{label}: vega_lite {problem}" for problem in validate_vega_lite(payload["vega_lite"])]
    bindings = payload.get("bindings") or []
    if not bindings:
        errors.append(f"{label}: no bindings")
    statements = [Statement("chart", "", str(b.get("value_exact")), b.get("source_ref"), f"{label}/binding{i}") for i, b in enumerate(bindings)]
    return len(bindings), errors + validate_statements(statements, lookup)
