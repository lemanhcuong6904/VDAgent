"""Golden fixtures (system prompt §7) layered on the background data of the DW mock.

Unit numbers below 20 are reserved for these rows. Floor bands are stored as §7.1 states them (DEC-033: A06-01 is
LOW and B15-02 HIGH although the semantic layer's cut-offs would say MID — TODO(spec-gap) G-14).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

REFERENCE_DAY = date(2026, 9, 28)  # DOM values below are as of the latest approved snapshot


@dataclass(frozen=True)
class FixtureUnit:
    code: str
    zone: str
    unit_type: str
    area: str
    floor_no: int
    band: str
    orientation: str
    view: str
    batch: str
    status: str  # at REFERENCE_DAY
    dom: int
    net_per_m2: int
    project: str = "PRJ-X"
    diag: dict[str, object] = field(default_factory=dict)
    bridge: tuple[tuple[str, str], ...] = ()  # (cause_code, attribution) by rank
    asking_missing: bool = False


def _hero_set() -> list[FixtureUnit]:
    def peer(code: str, zone: str, area: str, band: str, orient: str, view: str, price: int, dom: int, batch: str = "LB-02") -> FixtureUnit:
        return FixtureUnit(code, zone, "2PN", area, int(code[1:3]), band, orient, view, batch, "AVAILABLE", dom, price)

    overpriced = {"price_spread_vs_peer_pct": "12.40", "physical_defect_penalty": 5, "thermal_view_penalty": 10}
    return [
        FixtureUnit("A12-08", "ZN-A", "2PN", "68.50", 12, "MID", "SE", "CITY_OPEN", "LB-02", "AVAILABLE", 138,
                    72_500_000, diag=overpriced, bridge=(("OVERPRICED_VS_PEER", "1.000"),)),
        # 7 peers (§7.1), prices and DOM per DEC-030
        peer("A12-11", "ZN-A", "70.20", "MID", "SE", "CITY_OPEN", 67_000_000, 46),
        peer("A10-02", "ZN-A", "66.00", "MID", "SE", "CITY_OPEN", 64_500_000, 61),
        peer("A14-03", "ZN-A", "69.00", "MID", "S", "CITY_OPEN", 69_000_000, 42),
        peer("A06-01", "ZN-A", "67.10", "LOW", "SE", "CITY_OPEN", 62_500_000, 80),
        peer("B09-05", "ZN-B", "64.60", "MID", "SE", "CITY_OPEN", 61_500_000, 86),
        peer("B11-07", "ZN-B", "72.20", "MID", "SE", "INTERNAL_COURT", 60_000_000, 105),
        peer("B15-02", "ZN-B", "74.00", "HIGH", "SE", "CITY_OPEN", 70_000_000, 30, batch="LB-03"),
        # 5 candidates excluded at L0, "near misses" first
        FixtureUnit("C05-02", "ZN-C", "2PN", "68.00", 5, "LOW", "SE", "CITY_OPEN", "LB-01", "AVAILABLE", 40, 66_000_000),
        FixtureUnit("A16-01", "ZN-A", "2PN", "90.00", 16, "MID", "SE", "CITY_OPEN", "LB-02", "AVAILABLE", 70, 65_000_000),
        FixtureUnit("A08-09", "ZN-A", "2PN", "45.00", 8, "MID", "SE", "CITY_OPEN", "LB-02", "AVAILABLE", 75, 63_000_000),
        FixtureUnit("A13-06", "ZN-A", "2PN", "68.90", 13, "MID", "SE", "CITY_OPEN", "LB-02", "SOLD", 55, 66_500_000),
        FixtureUnit("A11-04", "ZN-A", "3PN", "69.50", 11, "MID", "SE", "CITY_OPEN", "LB-02", "AVAILABLE", 65, 64_000_000),
        # out of Alice's scope, same batch (GC-14, permissionFilteredCount)
        FixtureUnit("D12-09", "ZN-D", "2PN", "68.00", 12, "MID", "SE", "CITY_OPEN", "LB-02", "AVAILABLE", 100,
                    63_000_000, project="PRJ-Y"),
    ]


def _insight_set() -> list[FixtureUnit]:
    units = [
        # TC-01
        FixtureUnit("A-05.03", "ZN-A", "2PN", "66.00", 5, "LOW", "E", "CITY_OPEN", "LB-21", "AVAILABLE", 145, 70_000_000,
                    diag={"price_spread_vs_peer_pct": "12.40", "physical_defect_penalty": 5, "thermal_view_penalty": 8},
                    bridge=(("OVERPRICED_VS_PEER", "1.000"),)),
        # TC-02
        FixtureUnit("A-07.01", "ZN-A", "2PN", "67.00", 7, "MID", "W", "RIVER", "LB-21", "AVAILABLE", 160, 69_000_000,
                    diag={"price_spread_vs_peer_pct": "9.10", "physical_defect_penalty": 30, "thermal_view_penalty": 20},
                    bridge=(("OVERPRICED_VS_PEER", "0.500"), ("SEVERE_PHYSICAL_DEFECT", "0.300"),
                            ("LOW_SALES_INCENTIVE", "0.200"))),
        # TC-05 boundaries: none of them is overdue
        FixtureUnit("A03-01", "ZN-A", "1PN", "50.00", 3, "LOW", "N", "PARK", "LB-21", "AVAILABLE", 90, 60_000_000),
        FixtureUnit("A03-02", "ZN-A", "1PN", "50.00", 3, "LOW", "N", "PARK", "LB-21", "SOLD", 150, 60_000_000),
        FixtureUnit("A03-03", "ZN-A", "1PN", "50.00", 3, "LOW", "N", "PARK", "LB-21", "BOOKED", 120, 60_000_000),
    ]
    # TC-03 / TC-10 / TC-19 / TC-21: Tòa Aqua 1 has 40 overdue units; 25 face W and 2 NE; 12 lack diagnostics
    # (28/40 complete) and the asking price (30 % missing).
    others = ["N", "E", "SE", "S", "SW", "NW"]
    causes = ["OVERPRICED_VS_PEER", "EXTREME_THERMAL_EXPOSURE", "DEEP_FUNNEL_DROP_OFF", "LOW_SALES_INCENTIVE"]
    for i in range(40):
        floor_no, number = 6 + i // 2, 1 + i % 2
        orientation = "W" if i < 25 else "NE" if i < 27 else others[(i - 27) % len(others)]
        incomplete = i >= 28
        units.append(
            FixtureUnit(
                f"C{floor_no:02d}-{number:02d}", "ZN-C", "2PN", "65.00", floor_no, "MID", orientation, "CITY_OPEN",
                "LB-22", "AVAILABLE", 95 + 3 * i, 61_000_000 + 100_000 * i,
                diag={} if incomplete else {
                    "price_spread_vs_peer_pct": str(Decimal(i) / 4 + 2), "physical_defect_penalty": 10,
                    "thermal_view_penalty": 60 if orientation == "W" else 15,
                },
                bridge=((causes[i % len(causes)], "1.000"),),
                asking_missing=incomplete,
            )
        )
    return units


FIXTURE_UNITS = _hero_set() + _insight_set()


def _key(unit: FixtureUnit) -> str:
    return f"U-{unit.project}-{unit.code}"


def apply(conn: sqlite3.Connection, loads: list[date], date_key: object) -> None:
    """Insert fixture units, their inventory rows for every load, diagnostics and cause bridge."""
    to_key = date_key  # callable date -> int
    for unit in FIXTURE_UNITS:
        if unit.status == "SOLD":
            sold_date: date | None = REFERENCE_DAY - timedelta(days=10)
            release = sold_date - timedelta(days=unit.dom)
        else:
            sold_date = None
            release = REFERENCE_DAY - timedelta(days=unit.dom)
        area = Decimal(unit.area)
        conn.execute(
            "INSERT INTO dim_unit_master VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _key(unit), unit.code, unit.project, unit.zone, unit.unit_type, unit.area,
                str((area * Decimal("0.92")).quantize(Decimal("0.01"))), unit.floor_no, unit.band, unit.orientation,
                unit.view, unit.batch, release.isoformat(),
            ),
        )
        asking = None if unit.asking_missing else int((unit.net_per_m2 * area * Decimal("1.1")).quantize(Decimal("1E6")))
        for day in loads:
            if release > day:
                continue
            snap = to_key(day)  # type: ignore[operator]
            if sold_date is not None and sold_date <= day:
                status, dom, sold = "SOLD", unit.dom, sold_date.isoformat()
            else:
                status = unit.status if unit.status != "SOLD" else "AVAILABLE"
                dom, sold = (day - release).days, None
            conn.execute(
                "INSERT INTO fact_unit_inventory_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_key(unit), snap, unit.project, unit.zone, "CH-01", status, dom, release.isoformat(), day.isoformat(),
                 sold, asking, unit.net_per_m2),
            )
            overdue = status == "AVAILABLE" and dom > 90
            bridge = unit.bridge if overdue else ()
            for rank, (cause, score) in enumerate(bridge, start=1):
                conn.execute("INSERT INTO unit_diagnostic_causes VALUES (?, ?, ?, ?, ?)", (_key(unit), snap, cause, rank, score))
            d = unit.diag
            conn.execute(
                "INSERT INTO dm_unit_friction_diagnostics (unit_key, snapshot_date_key, primary_cause_code,"
                " price_spread_vs_peer_pct, is_peer_sample_constrained, peer_n, physical_defect_penalty,"
                " thermal_view_penalty) VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    _key(unit), snap, bridge[0][0] if bridge else None, d.get("price_spread_vs_peer_pct"),
                    7 if d else None, d.get("physical_defect_penalty"), d.get("thermal_view_penalty"),
                ),
            )
        conn.execute(
            "INSERT INTO fact_unit_price_history VALUES (?, ?, ?, ?)",
            (_key(unit), release.isoformat(), asking or 0, unit.net_per_m2),
        )
