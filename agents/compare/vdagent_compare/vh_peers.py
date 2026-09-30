"""Peer selection and exclusion explanations under the approved Compare v5.1 rule."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from .vh_data import Unit
from .vh_math import number, rounded, SIX

FLOOR_BANDS = ("LOW", "MID", "HIGH", "TOP")
ORIENTATION_GROUP = {
    "S": "COOL", "SE": "COOL", "E": "COOL",
    "W": "HOT", "SW": "HOT", "NW": "HOT",
    "N": "NORTH", "NE": "NORTH",
}
WEIGHTS = {
    "area_m2": Decimal("0.30"),
    "floor_band": Decimal("0.25"),
    "balcony_orientation": Decimal("0.20"),
    "view_type": Decimal("0.15"),
    "zone_id": Decimal("0.10"),
}
REASON_PRIORITY = {
    "below_similarity_cutoff": 0, "different_floor_band": 1,
    "out_of_area_band": 2, "different_orientation_group": 2,
    "different_launch_batch": 2, "mismatch_required_attribute": 2,
    "not_available": 2, "different_unit_type": 3,
}


@dataclass(frozen=True)
class PeerOutcome:
    status: str
    reason_code: str | None
    peers: list[dict]
    peer_count: int
    qualified_ids: frozenset[str]
    criteria: dict
    relaxation: dict
    attempts: list[dict]
    excluded_peers: list[dict]
    excluded_summary: dict[str, int]


def _criteria(subject: Unit, snapshot_id: str, scope: Mapping[str, object],
              area_pct: Decimal, must_match: list[str], floor_bands: list[str]) -> dict:
    return {
        "hard": {
            "snapshotId": snapshot_id,
            "unitType": subject.unit_type,
            "status": "available",
            "scope": {
                "userId": str(scope.get("userId", "")),
                "allowedProjectIds": list(scope.get("allowedProjectIds") or []),
                "allowedZoneIds": list(scope.get("allowedZoneIds") or []),
            },
            "mustMatch": must_match,
            "launchBatchId": subject.launch_batch_id,
            "areaTolerancePct": number(area_pct),
            "orientationGroup": ORIENTATION_GROUP[subject.balcony_orientation],
        },
        "eligibility": {"floorBands": floor_bands},
        "weights": {key: number(value) for key, value in WEIGHTS.items()},
    }


def _reason(unit: Unit, subject: Unit, area_pct: Decimal, must_match: list[str],
            floor_bands: list[str]) -> str | None:
    if unit.unit_type != subject.unit_type:
        return "different_unit_type"
    if unit.status != "available":
        return "not_available"
    if any(unit.attribute(dim) != subject.attribute(dim) for dim in must_match):
        return "mismatch_required_attribute"
    if unit.launch_batch_id != subject.launch_batch_id:
        return "different_launch_batch"
    if abs(unit.area_m2 - subject.area_m2) > subject.area_m2 * area_pct / 100:
        return "out_of_area_band"
    if ORIENTATION_GROUP.get(unit.balcony_orientation) != ORIENTATION_GROUP[subject.balcony_orientation]:
        return "different_orientation_group"
    if unit.floor_band not in floor_bands:
        return "different_floor_band"
    return None


def _score(subject: Unit, peer: Unit, area_pct: Decimal) -> dict:
    tolerance = subject.area_m2 * area_pct / 100
    parts = {
        "area_m2": max(Decimal(0), Decimal(1) - abs(peer.area_m2 - subject.area_m2) / tolerance),
        "floor_band": max(
            Decimal(0),
            Decimal(1) - Decimal(abs(FLOOR_BANDS.index(peer.floor_band) - FLOOR_BANDS.index(subject.floor_band))) / 3,
        ),
        "balcony_orientation": (
            Decimal(1) if peer.balcony_orientation == subject.balcony_orientation
            else Decimal("0.5") if ORIENTATION_GROUP[peer.balcony_orientation] == ORIENTATION_GROUP[subject.balcony_orientation]
            else Decimal(0)
        ),
        "view_type": Decimal(int(peer.view_type == subject.view_type)),
        "zone_id": Decimal(int(peer.zone_id == subject.zone_id)),
    }
    matched = [dim for dim, score in parts.items() if score >= Decimal("0.99")]
    differs = [
        {"dimension": dim, "subject": number(subject.attribute(dim)) if dim == "area_m2" else subject.attribute(dim),
         "peer": number(peer.attribute(dim)) if dim == "area_m2" else peer.attribute(dim)}
        for dim, score in parts.items() if score < Decimal("0.99")
    ]
    total = rounded(sum((parts[dim] * WEIGHTS[dim] for dim in parts), Decimal(0)), SIX)
    return {
        "entityId": peer.unit_id, "entityCode": peer.unit_code,
        "similarityScore": number(total), "matchedOn": matched, "differsOn": differs,
    }


def build_peer_group(subject: Unit, pool: list[Unit], *, snapshot_id: str,
                     scope: Mapping[str, object], area_pct: Decimal = Decimal(10),
                     min_peers: int = 5, relax: bool = True,
                     must_match: list[str] | None = None,
                     max_peers: int | None = None, max_excluded: int = 20) -> PeerOutcome:
    match = list(dict.fromkeys(must_match or []))
    if not set(match) <= {"balcony_orientation", "view_type", "zone_id"}:
        raise ValueError("INVALID_INPUT: mustMatch contains an unsupported attribute")
    if not Decimal(5) <= area_pct <= Decimal(10):
        raise ValueError("INVALID_INPUT: areaBandPct must be between 5 and 10")
    bands = [subject.floor_band]
    attempts: list[dict] = []
    scored: list[dict] = []
    level = 0
    for level in range(2 if relax else 1):
        if level:
            center = FLOOR_BANDS.index(subject.floor_band)
            bands = [band for i, band in enumerate(FLOOR_BANDS) if abs(i - center) <= 1]
        selected = [
            u for u in pool if u.unit_id != subject.unit_id and
            _reason(u, subject, area_pct, match, bands) is None
        ]
        scored = [_score(subject, u, area_pct) for u in selected]
        scored.sort(key=lambda row: (-row["similarityScore"], row["entityId"]))
        if max_peers is not None:
            scored = scored[:max_peers]
        summary = (
            f"{subject.unit_type}, đợt {subject.launch_batch_id}, diện tích ±{number(area_pct)}%, "
            f"hướng {ORIENTATION_GROUP[subject.balcony_orientation]}, tầng {'+'.join(bands)}"
        )
        attempts.append({"level": level, "peerCount": len(scored), "criteriaSummary": summary})
        if len(scored) >= min_peers:
            break
    count = len(scored)
    qualified = frozenset(row["entityId"] for row in scored)
    excluded_rows = []
    for unit in pool:
        if unit.unit_id == subject.unit_id or unit.unit_id in qualified:
            continue
        reason = _reason(unit, subject, area_pct, match, bands) or "below_similarity_cutoff"
        excluded_rows.append({
            "entityId": unit.unit_id, "entityCode": unit.unit_code,
            "reason": reason, "_areaDiff": abs(unit.area_m2 - subject.area_m2),
        })
    summary: dict[str, int] = {}
    for row in excluded_rows:
        summary[row["reason"]] = summary.get(row["reason"], 0) + 1
    excluded_rows.sort(key=lambda row: (REASON_PRIORITY[row["reason"]], row["_areaDiff"], row["entityId"]))
    excluded = [
        {key: value for key, value in row.items() if key != "_areaDiff"}
        for row in excluded_rows[:max_excluded]
    ]
    constrained = level > 0
    return PeerOutcome(
        status="VALID" if count >= min_peers else "PARTIAL",
        reason_code=None if count >= min_peers else "INSUFFICIENT_EVIDENCE",
        peers=scored if count >= min_peers else [],
        peer_count=count, qualified_ids=qualified,
        criteria=_criteria(subject, snapshot_id, scope, area_pct, match, bands),
        relaxation={
            "level": level, "relaxedDimensions": ["floor_band"] if constrained else [],
            "isPeerSampleConstrained": constrained,
            **({"reason": f"peerCount < {min_peers} ở nhóm tầng của đối tượng, đã mở sang nhóm tầng liền kề"} if constrained else {}),
        },
        attempts=attempts, excluded_peers=excluded, excluded_summary=summary,
    )


class UpstreamPeerSetError(ValueError):
    """Data's peer_set breaks an invariant Compare can check; the whole package is rejected."""


PEER_TIERS = ("strict", "expanded", "excluded")


def read_peer_set(subject: Unit, units: Mapping[str, Unit], peer_set: Mapping[str, object], *,
                  snapshot_id: str, scope: Mapping[str, object], area_pct: Decimal = Decimal(10),
                  min_peers: int = 5, must_match: list[str] | None = None,
                  area_override: Decimal | None = None, max_peers: int | None = None) -> PeerOutcome:
    """Spec v5.3 §1.5: Data applied the peer rule (and widened the floor band if needed).

    Every strict/expanded row is a peer. Compare only checks invariants (known unit, not the
    subject, same project / launch batch / unit type), narrows on an explicit user request
    and orders by similarity. It never removes a peer silently and never widens.
    """
    rows = peer_set.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise UpstreamPeerSetError("peer_set.rows phải là danh sách dòng.")
    match = list(dict.fromkeys(must_match or []))
    if not set(match) <= {"balcony_orientation", "view_type", "zone_id"}:
        raise ValueError("INVALID_INPUT: mustMatch contains an unsupported attribute")
    peers: list[tuple[Unit, str]] = []
    excluded: list[dict] = []
    for row in rows:
        key, tier = row.get("unit_key"), row.get("match_tier")
        if tier not in PEER_TIERS:
            raise UpstreamPeerSetError(f"peer_set có match_tier không hợp lệ: {tier!r}.")
        unit = units.get(str(key))
        if unit is None:
            raise UpstreamPeerSetError(f"peer_set có unit_key {key} không có trong gói dữ liệu.")
        if tier == "excluded":
            excluded.append({"entityId": unit.unit_id, "entityCode": unit.unit_code,
                             "reason": str(row.get("exclusion_reason") or "excluded_by_data")})
            continue
        if unit.unit_id == subject.unit_id:
            raise UpstreamPeerSetError("peer_set chứa chính căn đối tượng.")
        broken = [label for ok, label in (
            (unit.project_id == subject.project_id, "dự án"),
            (unit.launch_batch_id == subject.launch_batch_id, "đợt mở bán"),
            (unit.unit_type == subject.unit_type, "loại căn"),
        ) if not ok]
        if broken:
            raise UpstreamPeerSetError(f"peer_set có căn {unit.unit_code} khác {', '.join(broken)} với đối tượng.")
        peers.append((unit, tier))
    narrowed = [
        (unit, tier) for unit, tier in peers
        if all(unit.attribute(dim) == subject.attribute(dim) for dim in match)
        and (area_override is None or abs(unit.area_m2 - subject.area_m2) <= subject.area_m2 * area_override / 100)
    ]
    scored = sorted((_score(subject, unit, area_pct) for unit, _ in narrowed),
                    key=lambda row: (-row["similarityScore"], row["entityId"]))
    if max_peers is not None:
        scored = scored[:max_peers]
    count = len(scored)
    constrained = bool(peer_set.get("isPeerSampleConstrained")) or any(tier == "expanded" for _, tier in narrowed)
    bands = sorted({unit.floor_band for unit, _ in narrowed} | {subject.floor_band}, key=FLOOR_BANDS.index)
    criteria = _criteria(subject, snapshot_id, scope, area_override or area_pct, match, bands)
    criteria["hard"]["status"] = "any"  # the team rule has no status criterion; DOM uses units for sale
    summary: dict[str, int] = {}
    for row in excluded:
        summary[row["reason"]] = summary.get(row["reason"], 0) + 1
    level = 1 if constrained else 0
    return PeerOutcome(
        status="VALID" if count >= min_peers else "PARTIAL",
        reason_code=None if count >= min_peers else "INSUFFICIENT_EVIDENCE",
        peers=scored if count >= min_peers else [],
        peer_count=count, qualified_ids=frozenset(row["entityId"] for row in scored),
        criteria=criteria,
        relaxation={
            "level": level, "relaxedDimensions": ["floor_band"] if constrained else [],
            "isPeerSampleConstrained": constrained, "source": "data",
            **({"reason": "Data đã mở sang nhóm tầng liền kề (match_tier = expanded)"} if constrained else {}),
        },
        attempts=[{"level": level, "peerCount": count,
                   "criteriaSummary": f"nhóm do Data chọn ({peer_set.get('packageId') or 'peer_set'})"}],
        excluded_peers=excluded[:20], excluded_summary=summary,
    )
