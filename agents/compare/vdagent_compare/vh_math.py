"""Deterministic decimal arithmetic for Compare. The model never computes these values."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

TWO = Decimal("0.01")
SIX = Decimal("0.000001")
DIRECTIONS = {
    "net_asking_price_per_m2": "neutral",
    "asking_price_per_m2": "neutral",
    "asking_price_vnd": "neutral",
    "dom": "lower_is_better",
    "unsold_days": "lower_is_better",
    "inquiry_leads_30d": "higher_is_better",
    "discount_pct": "neutral",
    "subsidy_duration_mo": "neutral",
    "absorption_rate": "higher_is_better",
    "conversion_rate": "higher_is_better",
    "velocity_30d": "higher_is_better",
}
GROUP_ONLY = {"absorption_rate", "conversion_rate", "velocity_30d"}
UNITS = {
    "net_asking_price_per_m2": "VND/m2",
    "asking_price_per_m2": "VND/m2",
    "asking_price_vnd": "VND",
    "dom": "days",
    "unsold_days": "days",
    "inquiry_leads_30d": "leads",
    "discount_pct": "percent",
    "subsidy_duration_mo": "months",
}
SOURCES = {
    "net_asking_price_per_m2": ("fact_unit_inventory_snapshot", ["net_price_per_m2"]),
    "asking_price_per_m2": ("fact_unit_inventory_snapshot", ["asking_price_per_m2"]),
    "asking_price_vnd": ("fact_unit_inventory_snapshot", ["asking_price_vnd"]),
    "dom": ("fact_unit_inventory_snapshot", ["unsold_days_dom"]),
    "unsold_days": ("fact_unit_inventory_snapshot", ["unsold_days_dom"]),
    "discount_pct": ("fact_unit_inventory_snapshot", ["discount_pct"]),
    "subsidy_duration_mo": ("fact_unit_inventory_snapshot", ["subsidy_duration_mo"]),
    "inquiry_leads_30d": ("fact_sales_funnel_daily", ["inquiry_leads_count"]),
}


def rounded(value: Decimal, places: Decimal = TWO) -> Decimal:
    return value.quantize(places, rounding=ROUND_HALF_UP)


def number(value: Decimal | int | None) -> int | float | None:
    if value is None:
        return None
    d = Decimal(value)
    return int(d) if d == d.to_integral_value() else float(d)


def benchmark(values: Iterable[Decimal | None], min_n: int = 5) -> dict | None:
    ordered = sorted(v for v in values if v is not None)
    if len(ordered) < min_n:
        return None

    def quantile(p: str) -> Decimal:
        index = Decimal(len(ordered) - 1) * Decimal(p)
        lo = int(index)
        hi = lo if index == lo else lo + 1
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)

    return {
        "stat": "median",
        "value": number(rounded(quantile("0.5"))),
        "p25": number(rounded(quantile("0.25"))),
        "p75": number(rounded(quantile("0.75"))),
        "mean": number(rounded(sum(ordered, Decimal(0)) / len(ordered))),
        "n": len(ordered),
    }


def threshold(metric: str) -> tuple[str, Decimal]:
    if metric == "discount_pct":
        return "abs", Decimal(2)
    if metric == "subsidy_duration_mo":
        return "abs", Decimal(3)
    if metric == "absorption_rate":
        return "abs", Decimal(5)
    if metric in {"net_asking_price_per_m2", "asking_price_per_m2", "asking_price_vnd"}:
        return "pct", Decimal(5)
    return "pct", Decimal(10)


def _exceeds(abs_gap: Decimal, pct_gap: Decimal | None, kind: str, limit: Decimal) -> bool:
    return abs(abs_gap) >= limit if kind == "abs" else pct_gap is not None and abs(pct_gap) >= limit


def compare_value(value: Decimal, bm: dict, peers: list[Decimal], metric: str, min_n: int = 5) -> dict:
    median = Decimal(str(bm["value"]))
    abs_gap = rounded(value - median)
    pct_gap = rounded((value - median) / median * 100) if median != 0 else None
    direction = DIRECTIONS[metric]
    kind, limit = threshold(metric)
    exceeds = _exceeds(abs_gap, pct_gap, kind, limit)
    if direction == "neutral":
        position = "higher" if abs_gap > 0 else "lower" if abs_gap < 0 else "inline"
    elif not exceeds:
        position = "inline"
    else:
        better = abs_gap > 0 if direction == "higher_is_better" else abs_gap < 0
        position = "better" if better else "worse"
    rank = 1 + sum(
        peer > value if direction == "higher_is_better" else peer < value
        for peer in peers
    )
    percentile = rounded(Decimal(100) * sum(peer <= value for peer in peers) / len(peers))
    materiality = "notable" if (
        bm["n"] >= min_n and exceeds and
        (value < Decimal(str(bm["p25"])) or value > Decimal(str(bm["p75"])))
    ) else "minor"
    result = {
        "absGap": number(abs_gap),
        "pctGap": number(pct_gap),
        "percentileRank": number(percentile),
        "rankInGroup": rank,
        "groupSize": len(peers) + 1,
        "position": position,
        "materiality": materiality,
    }
    result["thresholdAbs" if kind == "abs" else "thresholdPct"] = number(limit)
    return result


def confidence(count: int, min_n: int = 5, constrained: bool = False, partial: bool = False, stale: bool = False) -> str:
    if count < min_n:
        return "none"
    level = "high" if count >= 30 else "medium" if count >= 10 else "low"
    if level == "high" and (constrained or stale):
        level = "medium"
    if partial:
        level = "low"
    return level


def magnitude(metric_result: dict) -> str:
    if "thresholdAbs" in metric_result:
        ratio = abs(Decimal(str(metric_result["absGap"]))) / Decimal(str(metric_result["thresholdAbs"]))
        return "high" if ratio >= 3 else "medium" if ratio >= Decimal("1.5") else "low"
    pct = abs(Decimal(str(metric_result["pctGap"] or 0)))
    return "high" if pct >= 50 else "medium" if pct >= 10 else "low"
