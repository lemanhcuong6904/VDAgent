"""S6 verify (build spec 02 §5): grain, reconciliation, DQ rules, metrics with numerator/denominator/n (DEC-036/037).

Pure code, no LLM. Money and ratios are Decimal: RATIO values keep 4 decimals (so 12.40 % survives), every other unit
2 decimals, ROUND_HALF_UP.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from vdagent_data.semantic.loader import LAYER, Layer

_PLACES = {"RATIO": Decimal("0.0001")}
_DEFAULT_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class Problem:
    code: str  # DQ_BLOCKING
    detail: str


@dataclass(frozen=True)
class MetricValue:
    name: str
    formula_id: str
    unit: str
    numerator: int
    denominator: int | None
    n: int
    value: Decimal | None
    small_sample: bool


@dataclass(frozen=True)
class DqResult:
    rule: str
    status: Literal["PASS", "WARN", "FAIL"]
    affected: list[str] = field(default_factory=list)
    message: str = ""


def check_unique_grain(rows: Sequence[dict[str, Any]], key: list[str]) -> list[Problem]:
    counts = Counter(tuple(row[k] for k in key) for row in rows)
    duplicates = sorted("/".join(map(str, k)) for k, c in counts.items() if c > 1)
    if not duplicates:
        return []
    return [Problem("DQ_BLOCKING", f"grain {'+'.join(key)} not unique: {', '.join(duplicates[:5])}")]


def reconcile(groups: Sequence[dict[str, Any]], total: dict[str, Any], columns: list[str]) -> list[Problem]:
    """Additive columns summed over the groups must equal the ungrouped total."""
    problems = []
    for column in columns:
        summed = sum(int(g[column] or 0) for g in groups)
        if summed != int(total[column] or 0):
            problems.append(Problem("DQ_BLOCKING", f"{column}: groups sum to {summed}, total is {total[column]}"))
    return problems


def compute_metrics(rows: Sequence[dict[str, Any]], metrics: list[str], *, layer: Layer = LAYER) -> list[dict[str, MetricValue]]:
    out: list[dict[str, MetricValue]] = []
    for row in rows:
        values: dict[str, MetricValue] = {}
        for name in metrics:
            metric = layer.metrics[name]
            numerator = int(row[f"{name}__num"] or 0)
            denominator = None if metric.denominator is None else int(row[f"{name}__den"] or 0)
            n = int(row.get("n", denominator if denominator is not None else numerator) or 0)
            if denominator is None:
                value: Decimal | None = Decimal(numerator)
                size = n
            elif denominator == 0:
                value, size = None, 0
            else:
                places = _PLACES.get(metric.unit, _DEFAULT_PLACES)
                value = (Decimal(numerator) / Decimal(denominator)).quantize(places, rounding=ROUND_HALF_UP)
                size = denominator
            values[name] = MetricValue(
                name=name, formula_id=metric.formula_id, unit=metric.unit, numerator=numerator,
                denominator=denominator, n=n, value=value, small_sample=size < metric.min_n,
            )
        out.append(values)
    return out


def dq_rules(units: Sequence[dict[str, Any]]) -> list[DqResult]:
    """Unit-grain DQ rules (E7 planted errors). Duplicate keys block; the rest warn."""
    keys = Counter(u["unit_key"] for u in units)
    duplicates = sorted(k for k, c in keys.items() if c > 1)
    bad_sold = sorted(
        u["unit_key"]
        for u in units
        if u.get("inventory_status") == "SOLD"
        and (not u.get("sold_date") or u["sold_date"] < u["release_date"] or u["sold_date"] > u["snapshot_date"])
    )
    net_gt = sorted(
        {
            u["unit_key"]
            for u in units
            if u.get("asking_price_vnd") and u.get("net_price_per_m2") and u.get("area_m2")
            and Decimal(u["net_price_per_m2"]) * Decimal(str(u["area_m2"])) > Decimal(u["asking_price_vnd"])
        }
    )
    missing_asking = sorted({u["unit_key"] for u in units if "asking_price_vnd" in u and u["asking_price_vnd"] is None})

    def result(rule: str, affected: list[str], fail: bool, message: str) -> DqResult:
        status: Literal["PASS", "WARN", "FAIL"] = "PASS" if not affected else ("FAIL" if fail else "WARN")
        return DqResult(rule=rule, status=status, affected=affected, message=message if affected else "")

    return [
        result("DQ-DUP-KEY", duplicates, True, "Trùng khóa căn trong cùng snapshot"),
        result("DQ-SOLD-DATE", bad_sold, False, "Căn SOLD thiếu sold_date hoặc sold_date ngoài [release_date, snapshot]"),
        result("DQ-NET-GT-ASKING", net_gt, False, "Giá ròng × diện tích lớn hơn giá chào"),
        result("DQ-MISSING-ASKING", missing_asking, False, "Thiếu giá chào"),
    ]
