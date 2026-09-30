"""Golden fixtures planted in the DW mock (system prompt §7, DEC-030, DEC-033)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from vdagent_backend.re_warehouse import build
from vdagent_contracts.canonical import percentile_inc, q2

SNAP = 20260928
HERO = "U-PRJ-X-A12-08"
PEERS = ["A12-11", "A10-02", "A14-03", "A06-01", "B09-05", "B11-07", "B15-02"]
EXCLUDED = ["C05-02", "A16-01", "A08-09", "A13-06", "A11-04"]


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    path = str(tmp_path_factory.mktemp("re") / "re.db")
    build(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def unit(conn: sqlite3.Connection, code: str, project: str = "PRJ-X") -> sqlite3.Row:
    row = conn.execute(
        "SELECT m.*, f.inventory_status, f.unsold_days_dom, f.net_price_per_m2, f.asking_price_vnd"
        " FROM dim_unit_master m JOIN fact_unit_inventory_snapshot f USING (unit_key)"
        " WHERE m.project_key = ? AND m.unit_code = ? AND f.snapshot_date_key = ?",
        (project, code, SNAP),
    ).fetchone()
    assert row is not None, code
    return row


def test_a12_08_target_attributes(conn: sqlite3.Connection) -> None:
    hero = unit(conn, "A12-08")
    assert (hero["unit_key"], hero["zone_key"], hero["unit_type"], hero["area_m2"]) == (HERO, "ZN-A", "2PN", "68.50")
    assert (hero["floor_no"], hero["floor_band"], hero["balcony_orientation"]) == (12, "MID", "SE")
    assert (hero["view_primary_type"], hero["launch_batch_id"]) == ("CITY_OPEN", "LB-02")
    assert (hero["net_price_per_m2"], hero["unsold_days_dom"], hero["inventory_status"]) == (72_500_000, 138, "AVAILABLE")


def test_a12_08_has_12_candidates_in_lb_01_02_03(conn: sqlite3.Connection) -> None:
    codes = [
        r[0]
        for r in conn.execute(
            "SELECT unit_code FROM dim_unit_master WHERE project_key = 'PRJ-X'"
            " AND launch_batch_id IN ('LB-01','LB-02','LB-03') AND unit_key <> ? ORDER BY unit_code",
            (HERO,),
        )
    ]
    assert sorted(codes) == sorted(PEERS + EXCLUDED)


def _score(conn: sqlite3.Connection, code: str) -> Decimal:
    hero, peer = unit(conn, "A12-08"), unit(conn, code)
    bands = ["LOW", "MID", "HIGH", "TOP"]
    area = 1 - abs(Fraction(peer["area_m2"]) - Fraction(hero["area_m2"])) / (Fraction("0.10") * Fraction(hero["area_m2"]))
    floor = {0: Fraction(1), 1: Fraction(2, 3), 2: Fraction(1, 3)}.get(
        abs(bands.index(peer["floor_band"]) - bands.index(hero["floor_band"])), Fraction(0)
    )
    ring = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    step = abs(ring.index(peer["balcony_orientation"]) - ring.index(hero["balcony_orientation"])) % 8
    balcony = Fraction(1) if step == 0 else Fraction(1, 2) if min(step, 8 - step) == 1 else Fraction(0)
    view = Fraction(int(peer["view_primary_type"] == hero["view_primary_type"]))
    zone = Fraction(int(peer["zone_key"] == hero["zone_key"]))
    total = Fraction(3, 10) * area + Fraction(1, 4) * floor + Fraction(1, 5) * balcony + Fraction(3, 20) * view + Fraction(1, 10) * zone
    return (Decimal(total.numerator) / Decimal(total.denominator)).quantize(Decimal("0.0001"))


def test_peer_attributes_reproduce_similarity_scores(conn: sqlite3.Connection) -> None:
    expected = ["0.9255", "0.8905", "0.8781", "0.8554", "0.7292", "0.5880", "0.5758"]
    assert [str(_score(conn, code)) for code in PEERS] == expected


def test_peer_prices_give_median_p25_p75_mean(conn: sqlite3.Connection) -> None:
    prices = [Decimal(unit(conn, code)["net_price_per_m2"]) for code in PEERS]
    assert percentile_inc(prices, Decimal("0.5")) == 64_500_000
    assert (percentile_inc(prices, Decimal("0.25")), percentile_inc(prices, Decimal("0.75"))) == (62_000_000, 68_000_000)
    assert q2(sum(prices) / 7) == Decimal("64928571.43")
    assert q2((Decimal(72_500_000) - 64_500_000) / 64_500_000 * 100) == Decimal("12.40")


def test_peer_dom_give_median_p25_p75_mean(conn: sqlite3.Connection) -> None:
    dom = [Decimal(unit(conn, code)["unsold_days_dom"]) for code in PEERS]
    assert percentile_inc(dom, Decimal("0.5")) == 61
    assert (percentile_inc(dom, Decimal("0.25")), percentile_inc(dom, Decimal("0.75"))) == (44, 83)
    assert q2(sum(dom) / 7) == Decimal("64.29")


def test_out_of_scope_unit_same_batch_exists(conn: sqlite3.Connection) -> None:
    other = unit(conn, "D12-09", project="PRJ-Y")
    assert (other["launch_batch_id"], other["unit_type"], other["inventory_status"]) == ("LB-02", "2PN", "AVAILABLE")


def test_landmark_two_similar_zone_names(conn: sqlite3.Connection) -> None:
    names = [r[0] for r in conn.execute("SELECT zone_name FROM dim_zone_master WHERE zone_name LIKE '%Landmark%' ORDER BY 1")]
    assert names == ["Landmark Plaza", "Tòa Landmark 1"]


def _bridge(conn: sqlite3.Connection, code: str) -> list[tuple[str, int, str]]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT cause_code, severity_rank, attribution_score FROM unit_diagnostic_causes"
            " WHERE unit_key = ? AND snapshot_date_key = ? ORDER BY severity_rank",
            (f"U-PRJ-X-{code}", SNAP),
        )
    ]


def test_tc01_a_05_03(conn: sqlite3.Connection) -> None:
    row = unit(conn, "A-05.03")
    assert (row["inventory_status"], row["unsold_days_dom"]) == ("AVAILABLE", 145)
    assert _bridge(conn, "A-05.03") == [("OVERPRICED_VS_PEER", 1, "1.000")]
    diag = conn.execute(
        "SELECT primary_cause_code, price_spread_vs_peer_pct, physical_defect_penalty FROM dm_unit_friction_diagnostics"
        " WHERE unit_key = 'U-PRJ-X-A-05.03' AND snapshot_date_key = ?",
        (SNAP,),
    ).fetchone()
    assert tuple(diag) == ("OVERPRICED_VS_PEER", "12.40", 5)
    assert [c for c, *_ in _bridge(conn, "A-07.01")] and [s for *_, s in _bridge(conn, "A-07.01")] == ["0.500", "0.300", "0.200"]


def test_tc03_aqua1_40_overdue_28_complete(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT m.balcony_orientation, d.price_spread_vs_peer_pct, f.asking_price_vnd"
        " FROM fact_unit_inventory_snapshot f JOIN dim_unit_master m USING (unit_key)"
        " JOIN dm_unit_friction_diagnostics d ON d.unit_key = f.unit_key AND d.snapshot_date_key = f.snapshot_date_key"
        " WHERE f.snapshot_date_key = ? AND f.zone_key = 'ZN-C' AND f.inventory_status = 'AVAILABLE'"
        " AND f.unsold_days_dom > 90",
        (SNAP,),
    ).fetchall()
    assert len(rows) == 40
    assert sum(r[1] is not None for r in rows) == 28  # TC-21: 28/40 with complete diagnostics
    assert sum(r[2] is None for r in rows) == 12  # TC-10: 30% missing asking_price_vnd
    orientation = [r[0] for r in rows]
    assert (orientation.count("W"), orientation.count("NE")) == (25, 2)  # TC-19


def test_tc04_project_permit_false(conn: sqlite3.Connection) -> None:
    permit = conn.execute("SELECT is_sales_permit_issued FROM dim_project_profile WHERE project_key = 'PRJ-Z'").fetchone()[0]
    assert permit == 0


def test_tc05_boundary_units(conn: sqlite3.Connection) -> None:
    got = {code: (unit(conn, code)["inventory_status"], unit(conn, code)["unsold_days_dom"]) for code in ("A03-01", "A03-02", "A03-03")}
    assert got == {"A03-01": ("AVAILABLE", 90), "A03-02": ("SOLD", 150), "A03-03": ("BOOKED", 120)}
    assert all(_bridge(conn, code) == [] for code in got)
