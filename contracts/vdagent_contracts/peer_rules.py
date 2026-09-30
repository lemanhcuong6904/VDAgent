"""Peer-group area rules shared by Data and Compare (docs/integration/CANONICAL_DATA_CONTRACT.md §2).

D9 (approved): the peer area is `dim_unit_master.net_area_m2`; `area_m2` is never used in its place. The area
tolerance is a decimal ratio (0.10 = 10 %), as stored in `semantic_config.peer_area_tolerance_pct` of `sc-1`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

PEER_AREA_FIELD = "net_area_m2"
MIN_AREA_TOLERANCE = Decimal("0.05")
MAX_AREA_TOLERANCE = Decimal("0.10")


class PeerAreaUnavailable(ValueError):
    """The unit has no usable `net_area_m2`; the caller excludes it, it never substitutes `area_m2`."""


def _decimal(raw: Any) -> Decimal:
    if isinstance(raw, float):
        raise TypeError("float given: pass a Decimal or a decimal string")
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith('"'):  # semantic_config values are JSON: "0.10"
            text = str(json.loads(text)).strip()
        try:
            return Decimal(text)
        except InvalidOperation:
            raise ValueError(f"not a decimal: {raw!r}") from None
    raise ValueError(f"not a decimal: {raw!r}")


def area_tolerance_ratio(raw: Any) -> Decimal:
    """The peer area tolerance as a ratio in [0.05, 0.10]; a percent value such as 10 is rejected."""
    value = _decimal(raw)
    if value >= 1:
        raise ValueError(f"area tolerance must be a ratio (0.10 = 10 %), got {raw!r}")
    if not MIN_AREA_TOLERANCE <= value <= MAX_AREA_TOLERANCE:
        raise ValueError(f"area tolerance ratio must be within [0.05, 0.10], got {raw!r}")
    return value


def tolerance_percent(ratio: Decimal) -> Decimal:
    """Percent form of a checked ratio (0.10 → 10), for engines that take percents."""
    return area_tolerance_ratio(ratio) * 100


def peer_area(row: Mapping[str, Any]) -> Decimal:
    """`net_area_m2` of a unit row in m²; raises `PeerAreaUnavailable` if it is absent, empty, invalid or ≤ 0."""
    raw = row.get(PEER_AREA_FIELD)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise PeerAreaUnavailable(f"{PEER_AREA_FIELD} is missing")
    try:
        value = _decimal(raw) if not isinstance(raw, int) else Decimal(raw)
    except (TypeError, ValueError) as exc:
        raise PeerAreaUnavailable(f"{PEER_AREA_FIELD} is not a decimal: {raw!r}") from exc
    if not value.is_finite() or value <= 0:
        raise PeerAreaUnavailable(f"{PEER_AREA_FIELD} must be > 0, got {raw!r}")
    return value
