"""Real-estate DW mock (D7): `build(path)` rebuilds `re_warehouse.db` deterministically.

Background data comes from `random.Random(SEED)`; golden fixtures (system prompt §7) are layered on top by
`fixtures.apply`. Same code → same bytes of `iterdump()` → same `checksum`.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from vdagent_backend.re_warehouse import fixtures, semantic_config

SEED = 20260929
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

TABLES = (
    "snapshot_manifest",
    "semantic_config",
    "dim_project_profile",
    "dim_zone_master",
    "dim_unit_master",
    "dim_sales_channel",
    "fact_unit_inventory_snapshot",
    "fact_sales_channel_performance",
    "fact_unit_price_history",
    "fact_sales_funnel_daily",
    "dim_secondary_market_comps",
    "fact_market_macro_monthly",
    "dim_infrastructure_assets",
    "dm_unit_friction_diagnostics",
    "unit_diagnostic_causes",
)

# (snapshot_id, date, status)
SNAPSHOTS = [
    ("SNAP-2026-08-31", date(2026, 8, 31), "APPROVED"),
    ("SNAP-2026-09-28", date(2026, 9, 28), "APPROVED"),
    ("SNAP-2026-09-29", date(2026, 9, 29), "DRAFT"),
]
LATEST_APPROVED = "SNAP-2026-09-28"

PROJECTS = [
    # key, name, market, segment, permit, guarantee
    ("PRJ-X", "Khu đô thị Sông Xanh", "MKT-HCM-E", "HIGH_END", 1, 1),
    ("PRJ-Y", "Khu căn hộ Đồi Thông", "MKT-HCM-E", "MID_END", 1, 1),
    ("PRJ-Z", "Dự án Bến Cảng", "MKT-HCM-S", "MID_END", 0, 0),
]
ZONES = [
    # key, name, project, unit-code letter
    ("ZN-A", "Tòa Landmark 1", "PRJ-X", "A"),
    ("ZN-B", "Landmark Plaza", "PRJ-X", "B"),
    ("ZN-C", "Tòa Aqua 1", "PRJ-X", "C"),
    ("ZN-D", "Tòa Đồi Thông 1", "PRJ-Y", "D"),
    ("ZN-E", "Tòa Đồi Thông 2", "PRJ-Y", "E"),
    ("ZN-F", "Tòa Bến Cảng", "PRJ-Z", "F"),
]
CHANNELS = [
    ("CH-01", "Sàn Alpha", "2.0", 20_000_000),
    ("CH-02", "Sàn Beta", "1.2", 0),
    ("CH-03", "Bán trực tiếp", "0.5", 0),
]
ORIENTATIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
VIEWS = ["CITY_OPEN", "RIVER", "INTERNAL_COURT", "PARK"]
UNIT_TYPES = {"1PN": (45, 55), "2PN": (62, 75), "3PN": (85, 100)}
BACKGROUND_UNITS_PER_ZONE = 24
BACKGROUND_FIRST_NO = 20  # background unit numbers 20..; golden fixtures use numbers < 20
FIXTURE_ONLY_ZONES = {"ZN-C"}  # Tòa Aqua 1 holds exactly the TC-03 population
BRIDGE_SPLITS = [("1.000",), ("0.600", "0.400"), ("0.500", "0.300", "0.200")]


def date_key(day: date) -> int:
    return int(day.strftime("%Y%m%d"))


def floor_band(floor_no: int) -> str:
    if floor_no <= 5:
        return "LOW"
    if floor_no <= 20:
        return "MID"
    if floor_no <= 35:
        return "HIGH"
    return "TOP"


def _dec(value: Decimal, places: str = "0.01") -> str:
    return str(value.quantize(Decimal(places)))


def _base(conn: sqlite3.Connection) -> None:
    for snapshot_id, day, status in SNAPSHOTS:
        conn.execute(
            "INSERT INTO snapshot_manifest VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, date_key(day), status, semantic_config.CONFIG_VERSION, f"{day.isoformat()}T02:00:00Z"),
        )
    for key, value, status, description in semantic_config.ROWS:
        conn.execute(
            "INSERT INTO semantic_config VALUES (?, ?, ?, ?, ?)",
            (semantic_config.CONFIG_VERSION, key, json.dumps(value, ensure_ascii=False), status, description),
        )
    conn.executemany("INSERT INTO dim_project_profile VALUES (?, ?, ?, ?, ?, ?)", PROJECTS)
    conn.executemany("INSERT INTO dim_zone_master VALUES (?, ?, ?)", [z[:3] for z in ZONES])
    conn.executemany("INSERT INTO dim_sales_channel VALUES (?, ?, ?, ?)", CHANNELS)


def _background_units(conn: sqlite3.Connection, rng: random.Random) -> None:
    loads = [(sid, day) for sid, day, _ in SNAPSHOTS]  # every load, DRAFT included
    for zone_key, _name, project_key, letter in ZONES:
        if zone_key in FIXTURE_ONLY_ZONES:
            continue
        for i in range(BACKGROUND_UNITS_PER_ZONE):
            floor_no = rng.randint(2, 38)
            unit_code = f"{letter}{floor_no:02d}-{BACKGROUND_FIRST_NO + i:02d}"
            unit_key = f"U-{project_key}-{unit_code}"
            unit_type = rng.choice(sorted(UNIT_TYPES))
            low, high = UNIT_TYPES[unit_type]
            area = Decimal(rng.randint(low * 10, high * 10)) / 10
            release = date(2025, 6, 1) + timedelta(days=rng.randint(0, 365))
            batch = f"LB-1{1 + (release.toordinal() // 120) % 3}"  # golden fixtures own LB-01..03
            conn.execute(
                "INSERT INTO dim_unit_master VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    unit_key, unit_code, project_key, zone_key, unit_type, _dec(area), _dec(area * Decimal("0.92")),
                    floor_no, floor_band(floor_no), rng.choice(ORIENTATIONS), rng.choice(VIEWS), batch,
                    release.isoformat(),
                ),
            )
            net_per_m2 = rng.randint(550, 800) * 100_000
            asking = int((Decimal(net_per_m2) * area * Decimal("1.1")).quantize(Decimal("1E6")))
            sold_after = rng.choice([None, None, rng.randint(20, 200)])
            channel = rng.choice(CHANNELS)[0]
            for _snapshot_id, day in loads:
                sold_date = release + timedelta(days=sold_after) if sold_after is not None else None
                if sold_date is not None and sold_date <= day:
                    status, dom = "SOLD", sold_after
                else:
                    sold_date = None
                    status = "BOOKED" if rng.random() < 0.05 else "AVAILABLE"
                    dom = (day - release).days
                conn.execute(
                    "INSERT INTO fact_unit_inventory_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        unit_key, date_key(day), project_key, zone_key, channel, status, dom, release.isoformat(),
                        day.isoformat(), sold_date.isoformat() if sold_date else None, asking, net_per_m2,
                    ),
                )
                _diagnose(conn, rng, unit_key, date_key(day), status, dom)
            conn.execute(
                "INSERT INTO fact_unit_price_history VALUES (?, ?, ?, ?)",
                (unit_key, release.isoformat(), int(asking * 0.95) // 1_000_000 * 1_000_000, net_per_m2 * 95 // 100),
            )
            conn.execute(
                "INSERT INTO fact_unit_price_history VALUES (?, ?, ?, ?)",
                (unit_key, (release + timedelta(days=90)).isoformat(), asking, net_per_m2),
            )
            for d in range(3):
                leads = rng.randint(0, 12)
                bookings = min(leads, rng.randint(0, 2))
                conn.execute(
                    "INSERT INTO fact_sales_funnel_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        unit_key, date_key(date(2026, 9, 25) + timedelta(days=d)), leads, rng.randint(0, leads),
                        bookings, rng.randint(0, bookings), 0, "Khách đổi ý" if bookings else None,
                    ),
                )


def _diagnose(conn: sqlite3.Connection, rng: random.Random, unit_key: str, snap: int, status: str, dom: int) -> None:
    overdue = status == "AVAILABLE" and dom > 90
    causes: list[str] = []
    if overdue:
        split = rng.choice(BRIDGE_SPLITS)
        causes = rng.sample(sorted(semantic_config.CAUSES), len(split))
        for rank, (cause, score) in enumerate(zip(causes, split, strict=True), start=1):
            conn.execute("INSERT INTO unit_diagnostic_causes VALUES (?, ?, ?, ?, ?)", (unit_key, snap, cause, rank, score))
    conn.execute(
        "INSERT INTO dm_unit_friction_diagnostics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            unit_key, snap, causes[0] if causes else None, _dec(Decimal(rng.randint(-80, 160)) / 10), 0,
            rng.randint(8, 14), rng.randint(0, 40), rng.randint(0, 60), rng.randint(0, 36),
            _dec(Decimal(rng.randint(-50, 150)) / 10), _dec(Decimal(rng.randint(80, 200)) / 10),
            _dec(Decimal(rng.randint(100, 800)) / 10), _dec(Decimal(rng.randint(0, 900)) / 10),
            semantic_config.CAUSES[causes[0]]["action_code"] if causes else None,
        ),
    )


def _market(conn: sqlite3.Connection, rng: random.Random) -> None:
    for project_key, _n, market, segment, _p, _g in PROJECTS:
        for unit_type in sorted(UNIT_TYPES):
            for i in range(5):
                conn.execute(
                    "INSERT INTO dim_secondary_market_comps VALUES (?, ?, ?, ?, ?)",
                    (
                        f"SC-{project_key}-{unit_type}-{i}", project_key, unit_type,
                        (date(2026, 7, 1) + timedelta(days=rng.randint(0, 80))).isoformat(),
                        rng.randint(500, 750) * 100_000,
                    ),
                )
        for asset, kind in enumerate(["METRO", "SCHOOL", "MALL"]):
            conn.execute(
                "INSERT INTO dim_infrastructure_assets VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"IA-{project_key}-{asset}", project_key, kind, f"{kind.title()} {project_key}",
                    _dec(Decimal(rng.randint(3, 60)) / 10, "0.1"), rng.choice(["OPERATING", "UNDER_CONSTRUCTION"]),
                ),
            )
        for channel_key, *_ in CHANNELS:
            for _sid, day, _st in SNAPSHOTS:
                conn.execute(
                    "INSERT INTO fact_sales_channel_performance VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        channel_key, project_key, date_key(day), rng.randint(200, 5000), rng.randint(0, 12),
                        _dec(Decimal(rng.randint(50, 400)) / 10),
                    ),
                )
    for market, segment in sorted({(p[2], p[3]) for p in PROJECTS}):
        for month in (202509, 202608, 202609):
            conn.execute(
                "INSERT INTO fact_market_macro_monthly VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    market, segment, month, _dec(Decimal(rng.randint(80, 120)) / 10),
                    _dec(Decimal(rng.randint(150, 450)) / 10), _dec(Decimal(rng.randint(40, 180)) / 10),
                    _dec(Decimal(rng.randint(150, 300)) / 10),
                ),
            )


def build(path: str, *, seed: int = SEED) -> str:
    """Rebuild the DW mock at `path` from scratch; returns its checksum. Another `seed` shuffles the background data
    (eval variants, E2b) while the golden fixtures stay identical."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    rng = random.Random(seed)
    conn = sqlite3.connect(target)
    try:
        with conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            _base(conn)
            _background_units(conn, rng)
            _market(conn, rng)
            fixtures.apply(conn, [day for _sid, day, _st in SNAPSHOTS], date_key)
    finally:
        conn.close()
    return checksum(path)


def checksum(path: str) -> str:
    conn = sqlite3.connect(path)
    try:
        digest = hashlib.sha256("\n".join(conn.iterdump()).encode("utf-8")).hexdigest()
    finally:
        conn.close()
    return digest
