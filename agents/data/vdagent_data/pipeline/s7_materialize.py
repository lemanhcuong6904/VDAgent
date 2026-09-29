"""S7 materialize (build spec 02 §5, 00 §3.4): the immutable Data Package as a `data_package` artifact.

Each entry embeds its rows (PII columns dropped) with a content hash; `run_id` stays out of the payload so identical
content hashes identically across runs. The 3–5 line summary passes a sensor: every number in it must appear in the
package (retry once, then a deterministic template).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from vdagent_agentkit.mcp_client import McpSession
from vdagent_contracts.canonical import content_hash
from vdagent_contracts.envelope import ArtifactDraft, ArtifactStatus, Producer
from vdagent_data.pipeline.s6_verify import DqResult, MetricValue

AGENT_VERSION = "0.2.0"
SCHEMA_VERSION = "data_package@1"
# TODO(spec-gap): the DW v3.1.0 document lists the PII columns; these names are the conservative default.
PII_COLUMNS = frozenset({"customer_name", "customer_phone", "customer_email", "owner_name", "owner_phone", "national_id"})

_NUMBER = re.compile(r"(?<![\w\-/.,])[+\-]?\d[\d.,]*(?![\w\-])")


def _jsonable(value: Any) -> Any:
    if isinstance(value, float):
        raise TypeError("float in a Data Package")
    return value


@dataclass(frozen=True)
class PackageEntry:
    kind: str  # unit_set | metric_table | peer_candidates | unit_context
    dataset_id: str | None
    grain: str
    columns: list[str]
    rows: list[list[Any]]
    metrics: list[dict[str, dict[str, Any]]] = field(default_factory=list)
    dropped_pii: list[str] = field(default_factory=list)
    truncated: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def table(*, kind: str, dataset_id: str | None, grain: str, rows: Sequence[dict[str, Any]], truncated: bool = False,
              extra: dict[str, Any] | None = None) -> PackageEntry:
        columns = list(rows[0]) if rows else []
        dropped = sorted(c for c in columns if c in PII_COLUMNS)
        keep = [c for c in columns if c not in PII_COLUMNS]
        return PackageEntry(kind=kind, dataset_id=dataset_id, grain=grain, columns=keep,
                            rows=[[_jsonable(r[c]) for c in keep] for r in rows], dropped_pii=dropped,
                            truncated=truncated, extra=extra or {})

    @staticmethod
    def metric_table(*, dataset_id: str | None, grain: str, group_by: list[str], rows: Sequence[dict[str, Any]],
                     metrics: Sequence[dict[str, MetricValue]]) -> PackageEntry:
        entry = PackageEntry.table(kind="metric_table", dataset_id=dataset_id, grain=grain, rows=rows)
        rendered = [
            {
                name: {
                    "value": None if m.value is None else str(m.value), "numerator": m.numerator,
                    "denominator": m.denominator, "n": m.n, "formula_id": m.formula_id, "unit": m.unit,
                    "small_sample": m.small_sample,
                }
                for name, m in row.items()
            }
            for row in metrics
        ]
        groups = [{d: r.get(d) for d in group_by} for r in rows]
        return PackageEntry(kind="metric_table", dataset_id=dataset_id, grain=grain, columns=entry.columns,
                            rows=entry.rows, metrics=rendered, extra={"groups": groups, "group_by": group_by})

    def manifest(self) -> dict[str, Any]:
        content = {"kind": self.kind, "grain": self.grain, "columns": self.columns, "data": self.rows,
                   "metrics": self.metrics, **self.extra}
        return {
            **content,
            "dataset_id": self.dataset_id,
            "rows": len(self.rows),
            "truncated": self.truncated,
            "status": "PARTIAL" if self.truncated else "VALID",
            "content_hash": content_hash(content),
        }


def build_package(
    *,
    operation: str,
    snapshot_id: str,
    semantic_config_version: str,
    resolved: dict[str, Any],
    entries: Sequence[PackageEntry],
    dq: Sequence[DqResult],
    lineage: list[dict[str, Any]],
    summary: str,
    warnings: Sequence[str] = (),
    limitations: Sequence[str] = (),
    data_confidence: str | None = None,
    extra: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> ArtifactDraft:
    artifacts = [e.manifest() for e in entries]
    limits = list(limitations) + [f"{e.kind}: kết quả bị cắt bớt" for e in entries if e.truncated]
    dq_report = {
        "rules": [{"rule": r.rule, "status": r.status, "affected": r.affected, "message": r.message} for r in dq],
        "status": "FAIL" if any(r.status == "FAIL" for r in dq) else "WARN" if any(r.status == "WARN" for r in dq) else "PASS",
    }
    body: dict[str, Any] = {
        "operation": operation,
        "snapshot_id": snapshot_id,
        "semantic_config_version": semantic_config_version,
        "resolved": resolved,
        "artifacts": artifacts,
        "dq_report": dq_report,
        "lineage": lineage,
        "warnings": sorted(set(warnings)),
        "limitations": limits,
        "data_confidence": data_confidence,
        "pii_dropped": sorted({c for e in entries for c in e.dropped_pii}),
        **(extra or {}),
    }
    body["content_hash"] = content_hash(body)
    body["summary"] = summary  # outside the hash, like the run identity below
    body["idempotency_key"] = idempotency_key
    status = ArtifactStatus.PARTIAL if limits else ArtifactStatus.VALID
    return ArtifactDraft(
        artifact_type="data_package",
        schema_version=SCHEMA_VERSION,
        status=status,
        producer=Producer(agent="data", agent_version=AGENT_VERSION),
        snapshot_refs=[snapshot_id],
        semantic_config_version=semantic_config_version,
        source_refs=[a["dataset_id"] for a in artifacts if a["dataset_id"]],
        limitations=limits,
        payload=body,
    )


async def persist(session: McpSession, draft: ArtifactDraft, *, supersedes: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    if supersedes:
        draft = draft.model_copy(update={"artifact_id": supersedes})
    args: dict[str, Any] = {"draft_json": json.dumps(draft.model_dump(mode="json", exclude_none=True), ensure_ascii=False)}
    if run_id:
        args["run_id"] = run_id
    outcome = await session.call_tool("artifact_put", args)
    if outcome.is_error:
        raise RuntimeError(outcome.text)
    return json.loads(outcome.text)


# -- summary sensor ----------------------------------------------------------------------------------------------


def _parse_number(token: str) -> Decimal | None:
    raw = token.lstrip("+")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    raw = raw.rstrip(".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[Decimal]:
    """Numbers as a Vietnamese reader sees them (64.500.000 · 12,4 · 8/8); identifiers like A12-08 are skipped."""
    found = []
    for token in _NUMBER.findall(text.replace("%", " ").replace("/", " ")):
        value = _parse_number(token)
        if value is not None:
            found.append(value)
    return found


def _manifest_numbers(payload: dict[str, Any]) -> set[Decimal]:
    values: set[Decimal] = set()

    def add(value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int):
            values.add(Decimal(value))
        elif isinstance(value, str):
            try:
                values.add(Decimal(value))
            except InvalidOperation:
                return

    for artifact in payload.get("artifacts", []):
        add(artifact.get("rows"))
        for row in artifact.get("data", []):
            for cell in row:
                add(cell)
        for metrics in artifact.get("metrics", []):
            for metric in metrics.values():
                for key in ("value", "numerator", "denominator", "n"):
                    add(metric.get(key))
                if metric.get("unit") == "RATIO" and metric.get("value") is not None:
                    values.add(Decimal(metric["value"]) * 100)
    for key in ("peer_count", "hidden_rows", "permissionFilteredCount"):
        add(payload.get(key))
    return values


def unsupported_numbers(text: str, payload: dict[str, Any]) -> list[Decimal]:
    """Numbers in `text` that no package value explains (after rounding the package value to the text's precision)."""
    known = _manifest_numbers(payload)
    missing = []
    for number in numbers_in(text):
        places = Decimal(1).scaleb(number.as_tuple().exponent) if isinstance(number.as_tuple().exponent, int) else Decimal(1)
        if not any(k.quantize(places) == number for k in known if k.as_tuple().exponent is not None):
            missing.append(number)
    return missing


def template_summary(payload: dict[str, Any]) -> str:
    parts = []
    for artifact in payload.get("artifacts", []):
        parts.append(f"{artifact['kind']}: {artifact['rows']} dòng (grain {artifact['grain']})")
    status = payload.get("dq_report", {}).get("status", "PASS")
    return "Đã chuẩn bị dữ liệu — " + "; ".join(parts) + f". Kiểm tra chất lượng dữ liệu: {status}."


Summarizer = Callable[[dict[str, Any]], Awaitable[str]]


async def summarize(payload: dict[str, Any], summarizer: Summarizer | None) -> tuple[str, str]:
    """LLM summary checked by the numbers sensor; two failures (or no LLM) → template."""
    if summarizer is not None:
        for _ in range(2):
            text = (await summarizer(payload)).strip()
            if text and not unsupported_numbers(text, payload):
                return text, "LLM"
    return template_summary(payload), "TEMPLATE"
