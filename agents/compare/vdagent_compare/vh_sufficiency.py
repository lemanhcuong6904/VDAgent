"""How far a peer comparison may go with the data at hand (spec v5.3 §2.4).

Three levels, the same bands Insight uses (≥ 10 compare · 5–9 describe · < 5 hide):

- FULL          ≥ 10 peers, none from an adjacent floor band, every metric "full"
- LIMITED       at least one usable metric, but a smaller sample, an expanded floor band,
                a dropped metric or patchy coverage; the answer must lead with its limits
- INSUFFICIENT  < 5 peers, or no usable metric: no numbers are published

Per metric: `n` peers have a value among the `applicable` ones (DOM only counts units still
for sale); "full" needs n ≥ 10 and ≥ 80 % coverage, "limited" n ≥ 5 and ≥ 50 %, else "dropped".
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .vh_data import Unit
from .vh_math import number, rounded

FOR_SALE_ONLY = frozenset({"dom", "unsold_days"})
REASON_ORDER = ("SMALL_SAMPLE", "PEER_SAMPLE_CONSTRAINED", "METRIC_DROPPED", "LOW_COVERAGE")
LEVEL_LABELS = {"FULL": "Đầy đủ", "LIMITED": "Hạn chế", "INSUFFICIENT": "Không đủ"}
REASON_LABELS = {
    "SMALL_SAMPLE": "nhóm dưới 10 căn",
    "PEER_SAMPLE_CONSTRAINED": "đã tính cả nhóm tầng liền kề",
    "METRIC_DROPPED": "có chỉ số bị bỏ vì thiếu dữ liệu",
    "LOW_COVERAGE": "có chỉ số thiếu dữ liệu ở một phần nhóm",
}


def applies_to(metric: str, unit: Unit) -> bool:
    return metric not in FOR_SALE_ONLY or unit.status == "available"


def _metric_use(subject: Unit, peers: Sequence[Unit], metric: str, *, min_peers: int, full_peers: int,
                full_cov: Decimal, min_cov: Decimal) -> dict:
    applicable = [p for p in peers if applies_to(metric, p)]
    n = sum(p.metrics.get(metric) is not None for p in applicable)
    coverage = rounded(Decimal(n) * 100 / len(applicable)) if applicable else Decimal(0)
    if subject.metrics.get(metric) is None or n < min_peers or coverage < min_cov:
        use = "dropped"
    elif n >= full_peers and coverage >= full_cov:
        use = "full"
    else:
        use = "limited"
    return {"metric": metric, "n": n, "applicable": len(applicable), "coveragePct": number(coverage), "use": use}


def assess(subject: Unit, peers: Sequence[Unit], metrics: Sequence[str], *, constrained: bool,
           min_peers: int = 5, full_peers: int = 10, full_cov: Decimal | int = 80,
           min_cov: Decimal | int = 50) -> dict:
    """`dataSufficiency` for a peer group: level, reasons (fixed order) and one row per metric."""
    rows = [_metric_use(subject, peers, m, min_peers=min_peers, full_peers=full_peers,
                        full_cov=Decimal(full_cov), min_cov=Decimal(min_cov)) for m in metrics]
    reasons = set()
    if len(peers) < full_peers:
        reasons.add("SMALL_SAMPLE")
    if constrained:
        reasons.add("PEER_SAMPLE_CONSTRAINED")
    if len(peers) >= min_peers and any(row["use"] == "dropped" for row in rows):
        reasons.add("METRIC_DROPPED")  # below min_peers every metric drops; the sample is the reason
    for row in rows:
        if row["use"] == "limited":  # missing values → coverage; few units it applies to → sample
            reasons.add("LOW_COVERAGE" if Decimal(str(row["coveragePct"])) < Decimal(full_cov) else "SMALL_SAMPLE")
    if len(peers) < min_peers or not any(row["use"] != "dropped" for row in rows):
        level = "INSUFFICIENT"
    elif reasons:
        level = "LIMITED"
    else:
        level = "FULL"
    ordered = [r for r in REASON_ORDER if r in reasons]
    return {"level": level, "reasons": ordered, "perMetric": rows, "summary": summary(level, ordered, len(peers))}


def summary(level: str, reasons: Sequence[str], peer_count: int) -> str:
    """One Vietnamese sentence; LIMITED answers must open with it (spec §2.4)."""
    if level == "FULL":
        return f"So sánh đầy đủ: nhóm {peer_count} căn tương đồng, đủ dữ liệu."
    detail = ", ".join(REASON_LABELS[r] for r in reasons)
    if level == "LIMITED":
        return f"So sánh có giới hạn: nhóm {peer_count} căn tương đồng ({detail}); chỉ nên đọc như mô tả."
    return f"Không đủ dữ liệu để so sánh: nhóm {peer_count} căn tương đồng ({detail})."
