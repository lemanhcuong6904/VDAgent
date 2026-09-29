"""Deterministic VDAgent warehouse mock data for Vinhomes Smart City POC.

All transactional, price, inventory and diagnostic records are synthetic.
Public project material informs only tower naming and broad apartment types.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json
import random
import re
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "mock" / "vhsc_20260630"
CONTRACT = ROOT / "docs" / "data-warehouse-data-contract-v3.1.0.md"
RNG = random.Random(25092026)
SNAP = date(2026, 6, 30)
CAUSES = [
    "SEVERE_PHYSICAL_DEFECT", "EXTREME_THERMAL_EXPOSURE", "SECONDARY_ARBITRAGE",
    "LUMP_SUM_TICKET_BARRIER", "OVERPRICED_VS_PEER", "LOW_SALES_INCENTIVE",
    "DEEP_FUNNEL_DROP_OFF",
]
ALL_CAUSES = ["LEGAL_PERMIT_BARRIER", *CAUSES]
ACTIONS = {
    "LEGAL_PERMIT_BARRIER": "EXPEDITE_LEGAL_PROCEDURES",
    "SEVERE_PHYSICAL_DEFECT": "DEFECT_COMPENSATION_DISCOUNT",
    "EXTREME_THERMAL_EXPOSURE": "INSULATION_INTERIOR_PACKAGE",
    "SECONDARY_ARBITRAGE": "EXTENDED_PAYMENT_SCHEDULE",
    "LUMP_SUM_TICKET_BARRIER": "BANK_SUBSIDY_EXTENSION",
    "OVERPRICED_VS_PEER": "TARGETED_PRICE_CORRECTION",
    "LOW_SALES_INCENTIVE": "BOOST_BROKER_COMMISSION",
    "DEEP_FUNNEL_DROP_OFF": "SALES_PITCH_AUDIT",
}


def money(value: Decimal | int | float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value: Decimal | int | float, digits: int) -> str:
    quantum = Decimal("1").scaleb(-digits)
    return str(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def date_key(day: date) -> int:
    return int(day.strftime("%Y%m%d"))


def columns_from_contract() -> dict[str, list[str]]:
    columns: dict[str, list[str]] = {}
    table = None
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^### \d+\. `([a-z_]+)`$", line)
        if match:
            table = match.group(1)
            columns[table] = []
            continue
        match = re.match(r"^\| ([a-z][a-z0-9_]*) \| (?:VARCHAR|DECIMAL|INTEGER|BIGINT|SMALLINT|DATE|BOOLEAN|JSONB|TEXT)", line)
        if match and table:
            columns[table].append(match.group(1))
    assert len(columns) == 16 and sum(map(len, columns.values())) == 178
    return columns


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: dict[str, list[dict]] = {name: [] for name in columns_from_contract()}
    rows["snapshot_manifest"].append(dict(
        snapshot_id="SNAP-20260630-01", dataset_id="vdagent_dw_re", dataset_version="3.1.0",
        semantic_version="3.1.0", snapshot_date=SNAP, timezone="Asia/Ho_Chi_Minh",
        currency="VND", price_basis="ASKING_EXCL_VAT_EXCL_MAINT", area_basis="NET_INTERNAL_M2",
        source_system="ENTERPRISE_DW_RE",
    ))
    settings = {
        "overdue_threshold_days": ("90", "INTEGER"),
        "peer_min_size": ("5", "INTEGER"),
        "peer_area_tolerance_pct": ("10", "DECIMAL"),
        "secondary_gap_threshold_pct": ("15", "DECIMAL"),
        "overpriced_peer_threshold_pct": ("8", "DECIMAL"),
        "physical_penalty_threshold": ("25", "INTEGER"),
        "thermal_penalty_threshold": ("40", "INTEGER"),
        "pir_threshold": ("25", "DECIMAL"),
        "low_commission_threshold_pct": ("1.5", "DECIMAL"),
        "funnel_dropoff_threshold_pct": ("60", "DECIMAL"),
        "secondary_comp_max_age_days": ("90", "INTEGER"),
        "max_attribution_rank": ("3", "INTEGER"),
    }
    for key, (value, kind) in settings.items():
        rows["semantic_config"].append(dict(config_key=key, config_value=value, value_type=kind,
                                            semantic_version="3.1.0", approval_status="APPROVED",
                                            description=f"Synthetic POC rule: {key}"))
    day = date(2026, 1, 1)
    while day <= SNAP:
        q = (day.month - 1) // 3 + 1
        rows["dim_date"].append(dict(date_key=date_key(day), full_date=day, year=day.year,
                                     quarter=q, month=day.month, day_of_month=day.day,
                                     is_weekend=day.weekday() >= 5, fiscal_quarter=f"{day.year}-Q{q}"))
        day += timedelta(days=1)

    infrastructure = [
        (1, "INF-METRO-05", "Metro số 5", "URBAN_METRO", "PLANNING_APPROVED", 0),
        (2, "INF-METRO-06", "Metro số 6", "URBAN_METRO", "PLANNING_APPROVED", 0),
        (3, "INF-THANG-LONG", "Đại lộ Thăng Long", "EXPRESSWAY", "COMMERCIAL_OPERATION", 100),
        (4, "INF-RING-ROAD-3.5", "Vành đai 3.5", "RING_ROAD", "UNDER_CONSTRUCTION", 50),
    ]
    for key, ident, name, kind, stage, progress in infrastructure:
        rows["dim_infrastructure_assets"].append(dict(infra_key=key, infra_id=ident, infra_name=name,
             infra_type=kind, lifecycle_stage=stage, construction_progress_pct=dec(progress, 2),
             original_completion_year=None, revised_completion_year=None))

    for project_key, project_id, name, legal in [
        (1, "PRJ-VHSC-HN", "Vinhomes Smart City", True),
        (2, "PRJ-VHSC-LEGAL-MOCK", "VHSC future phase — fictional legal test", False),
    ]:
        rows["dim_project_profile"].append(dict(
            project_key=project_key, project_id=project_id, project_name=name,
            market_id="MKT-WEST-HN", market_name="Tây Hà Nội", province_city="Hà Nội",
            district="Nam Từ Liêm", developer_name="Vinhomes (synthetic POC profile)",
            developer_tier="TIER_1", developer_origin="DOMESTIC", segment="MID",
            construction_status="HANDED_OVER" if legal else "FOUNDATION",
            construction_progress_pct="100.00" if legal else "10.00",
            is_sales_permit_issued=legal, is_bank_guarantee_issued=legal,
            max_foreign_quota_exceeded=False, primary_infra_id="INF-THANG-LONG",
            distance_to_primary_infra_m=500, partner_bank_name=None, expected_handover_date=None,
        ))
    zone_labels = ["S1.01", "S1.02", "S2.01", "S2.02", "S3.01", "S4.01", "MOCK-LGL-01"]
    for zone_key, label in enumerate(zone_labels, 1):
        project_key = 1 if zone_key <= 6 else 2
        rows["dim_zone_master"].append(dict(
            zone_key=zone_key, zone_id=f"ZN-VHSC-{label.replace('.', '')}", project_key=project_key,
            zone_name=label, zone_type="HIGH_RISE_TOWER", total_floors=35, basement_floors=1,
            units_per_floor=19 if zone_key <= 4 else 30, passenger_elevators=6,
            elevator_ratio=dec(Decimal(19 if zone_key <= 4 else 30) / 6, 1),
            handover_standard="BASIC_FINISH",
        ))
    for key in range(1, 9):
        rows["dim_sales_channel"].append(dict(channel_key=key, channel_id=f"MOCK-AGENCY-{key:02d}",
            channel_name=f"Synthetic sales channel {key:02d}",
            channel_tier="INHOUSE" if key == 1 else "TIER_2_GENERAL",
            active_brokers_count=8 + key * 3))

    target_order = list(range(1, 1201))
    RNG.shuffle(target_order)
    sold_keys = set(target_order[:816])
    booked_keys = set(target_order[816:900])
    overdue_keys = target_order[900:1020]
    edge_overdue_key = overdue_keys[0]       # DOM = 91, included in diagnostics.
    edge_not_overdue_key = target_order[1020] # DOM = 90, excluded from diagnostics.
    cause_by_key = {key: CAUSES[i % len(CAUSES)] for i, key in enumerate(overdue_keys)}
    all_units = []
    inventory = []
    for unit_key in range(1, 1217):
        project_key = 1 if unit_key <= 1200 else 2
        zone_key = ((unit_key - 1) // 200) + 1 if project_key == 1 else 7
        cause = cause_by_key.get(unit_key, "LEGAL_PERMIT_BARRIER" if project_key == 2 else None)
        unit_type = ("STUDIO", "1PN", "2PN", "3PN")[unit_key % 4]
        if cause in {"SEVERE_PHYSICAL_DEFECT", "EXTREME_THERMAL_EXPOSURE", "SECONDARY_ARBITRAGE",
                     "OVERPRICED_VS_PEER", "DEEP_FUNNEL_DROP_OFF", "LEGAL_PERMIT_BARRIER"}:
            unit_type = "2PN"
        elif cause == "LUMP_SUM_TICKET_BARRIER":
            unit_type = "3PN"
        elif cause == "LOW_SALES_INCENTIVE":
            unit_type = "1PN"
        ranges = {"STUDIO": (28, 35), "1PN": (38, 48), "2PN": (55, 70), "3PN": (80, 95)}
        lo, hi = ranges[unit_type]
        area = Decimal(str(RNG.uniform(lo, hi))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cause == "LUMP_SUM_TICKET_BARRIER":
            area = Decimal("94.00")
        gross = (area / Decimal("0.85")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        floor = 2 + (unit_key * 7) % 33
        band = "LOW" if floor <= 5 else "MID" if floor <= 20 else "HIGH"
        orientation = ("E", "SE", "S", "N", "NE", "SW", "W", "NW")[unit_key % 8]
        if cause == "EXTREME_THERMAL_EXPOSURE":
            orientation = "W"
        trash = "1.5" if cause == "SEVERE_PHYSICAL_DEFECT" else "12.0"
        exposure = "0.80" if cause == "EXTREME_THERMAL_EXPOSURE" else ("0.45" if orientation in {"W", "SW", "NW"} else "0.05")
        unit_code = f"{zone_labels[zone_key-1]}-{floor:02d}.{(unit_key % 30) + 1:02d}"
        unit = dict(
            unit_key=unit_key, unit_id=f"VHSC-U-{unit_key:05d}", unit_code=unit_code,
            project_key=project_key, zone_key=zone_key, unit_type=unit_type,
            bedroom_count={"STUDIO": 0, "1PN": 1, "2PN": 2, "3PN": 3}[unit_type],
            bathroom_count=1 if unit_type in {"STUDIO", "1PN"} else 2,
            net_area_m2=str(area), gross_area_m2=str(gross), floor_number=floor,
            floor_band=band, balcony_orientation=orientation, door_orientation="N",
            view_primary_type="CITY_OPEN", is_corner_unit=(unit_key % 10 == 0),
            efficiency_ratio=dec(area / gross, 3), distance_to_trash_room_m=trash,
            is_adjacent_elevator=False, dark_bedroom_count=0, west_facing_exposure_pct=exposure,
            view_obstruction_distance_m="50.0", taboo_view_type="NONE", is_taboo_floor=floor in {4, 7, 13, 14},
            ext_attributes=json.dumps({"data_origin": "synthetic", "reference": "Vinhomes Smart City"}),
        )
        rows["dim_unit_master"].append(unit)
        all_units.append(unit)

        status = "SOLD" if unit_key in sold_keys else "BOOKED" if unit_key in booked_keys else "AVAILABLE"
        if unit_key == edge_overdue_key:
            release = date(2026, 3, 31)
        elif unit_key == edge_not_overdue_key:
            release = date(2026, 4, 1)
        elif cause:
            release = date(2026, 1, 5) + timedelta(days=(unit_key * 7) % 45)
        elif status == "AVAILABLE":
            release = date(2026, 5, 1) + timedelta(days=(unit_key * 3) % 35)
        else:
            release = date(2026, 1, 5) + timedelta(days=(unit_key * 11) % 95)
        sold_date = release + timedelta(days=20 + unit_key % 45) if status == "SOLD" else None
        dom = ((sold_date or SNAP) - release).days
        ppm = {"STUDIO": 55_000_000, "1PN": 50_000_000, "2PN": 48_000_000, "3PN": 45_000_000}[unit_type]
        if cause == "SECONDARY_ARBITRAGE":
            ppm = 60_000_000
        elif cause == "OVERPRICED_VS_PEER":
            ppm = 56_000_000
        asking = money(area * ppm)
        discount = "0.00" if cause in {"SEVERE_PHYSICAL_DEFECT", "OVERPRICED_VS_PEER", "SECONDARY_ARBITRAGE"} else "2.00"
        concession = 0
        net = money(Decimal(asking) * (1 - Decimal(discount) / 100) - concession)
        commission = "1.20" if cause == "LOW_SALES_INCENTIVE" or (cause and unit_key % 6 == 0) else "2.50"
        inv = dict(
            snapshot_date_key=date_key(SNAP), unit_key=unit_key, project_key=project_key,
            zone_key=zone_key, channel_key=1 + unit_key % 8, launch_batch_id="VHSC-2026-01",
            release_date=release, inventory_status=status, sold_date=sold_date,
            unsold_days_dom=dom, is_overdue_flag=status == "AVAILABLE" and dom > 90,
            asking_price_vnd=asking, discount_pct=discount, concession_value_vnd=concession,
            net_price_vnd=net, asking_price_per_m2=money(Decimal(asking) / area),
            net_price_per_m2=money(Decimal(net) / area), subsidy_duration_mo=12 if cause == "EXTREME_THERMAL_EXPOSURE" else 24,
            principal_grace_mo=12, base_commission_pct=commission, spiff_bonus_vnd=0,
            is_exclusive_lock=unit_key % 10 == 0,
        )
        rows["fact_unit_inventory_snapshot"].append(inv)
        inventory.append(inv)

    for comp_id in range(1, 97):
        kind = ("1PN", "2PN", "3PN")[(comp_id - 1) % 3]
        rows["dim_secondary_market_comps"].append(dict(
            comp_id=f"MOCK-COMP-{comp_id:04d}", project_id=f"MOCK-NEIGHBOR-{1 + comp_id % 4}",
            unit_type=kind, floor_band=("LOW", "MID", "HIGH")[comp_id % 3],
            balcony_orientation=("E", "SE", "W", "SW")[comp_id % 4],
            recorded_resale_date=SNAP - timedelta(days=1 + comp_id % 75),
            resale_price_per_m2_vnd={"1PN": 46_000_000, "2PN": 46_000_000, "3PN": 43_000_000}[kind] + (comp_id % 5) * 200_000,
            pink_book_status="PINK_BOOK_AVAILABLE" if comp_id % 2 else "SPA_ASSIGNMENT",
        ))
    for month in range(1, 7):
        end = date(2026, month + 1, 1) - timedelta(days=1)
        for segment in ("AFFORDABLE", "MID", "MID_HIGH", "LUXURY"):
            rows["fact_market_macro_monthly"].append(dict(
                macro_record_id=f"MOCK-MACRO-{month:02d}-{segment}", date_key=date_key(end),
                market_id="MKT-WEST-HN", segment=segment,
                floating_mortgage_rate_pct=dec(12.5 - month * 0.15, 2),
                months_of_inventory_moi=dec(8 + month * 0.2, 1),
                absorption_rate_pct=dec(17 + month * 0.5, 2),
                median_household_income_vnd=150_000_000,
                macro_price_to_income_ratio="25.0",
            ))

    funnel_totals = defaultdict(lambda: [0, 0, 0, 0])
    for inv in inventory:
        key = inv["unit_key"]
        cause = cause_by_key.get(key, "LEGAL_PERMIT_BARRIER" if key > 1200 else None)
        release = inv["release_date"]
        last_day = inv["sold_date"] or SNAP
        span = max(1, (last_day - release).days)
        for n in range(4):
            day = release + timedelta(days=min(span, max(0, (n + 1) * span // 5)))
            views = 4 + key % 3 if cause == "LOW_SALES_INCENTIVE" else 20 + (key + n) % 25
            visits = (key + n) % 3
            booking = 1 if n == 2 and key % 5 == 0 else 0
            cancelled = 0
            reason = None
            if cause == "DEEP_FUNNEL_DROP_OFF" and n == 2:
                views, visits, booking, cancelled, reason = 300, 30, 10, 8, "DEFECT_FOUND"
            rows["fact_sales_funnel_daily"].append(dict(
                funnel_event_id=len(rows["fact_sales_funnel_daily"]) + 1,
                date_key=date_key(day), unit_key=key, web_listing_views=views,
                inquiry_leads_count=max(1, views // 20), site_visits_count=visits,
                booking_reservations=booking, booking_cancellations=cancelled,
                cancellation_reason=reason,
            ))
            totals = funnel_totals[key]
            totals[0] += views
            totals[1] += visits
            totals[2] += booking
            totals[3] += cancelled
        if key <= 480:
            effective = min(last_day, release + timedelta(days=10))
            new_price = inv["asking_price_vnd"]
            old_price = new_price - 50_000_000
            rows["fact_unit_price_history"].append(dict(
                price_event_id=key, unit_key=key, effective_date_key=date_key(effective),
                old_asking_price_vnd=old_price, new_asking_price_vnd=new_price,
                price_change_pct=dec(Decimal(new_price - old_price) * 100 / old_price, 2),
                change_reason="CAMPAIGN",
            ))

    by_channel_project = defaultdict(list)
    for inv in inventory:
        by_channel_project[(inv["channel_key"], inv["project_key"])].append(inv)
    for (channel, project), assigned in sorted(by_channel_project.items()):
        sold = [x for x in assigned if x["inventory_status"] == "SOLD"]
        rows["fact_sales_channel_performance"].append(dict(
            snapshot_date_key=date_key(SNAP), channel_key=channel, project_key=project,
            assigned_units_count=len(assigned), sold_units_count=len(sold),
            absorption_rate_pct=dec(Decimal(len(sold)) * 100 / len(assigned), 2),
            avg_days_to_sell=round(sum(x["unsold_days_dom"] for x in sold) / len(sold)) if sold else None,
            locked_inventory_over_90d=sum(x["is_exclusive_lock"] and x["is_overdue_flag"] for x in assigned),
        ))

    peer_price = defaultdict(list)
    for unit, inv in zip(all_units, inventory):
        climate = "HOT" if unit["balcony_orientation"] in {"W", "SW", "NW"} else "COOL"
        peer_price[(unit["project_key"], unit["unit_type"], unit["floor_band"], climate)].append(
            (unit["unit_key"], Decimal(unit["net_area_m2"]), inv["net_price_per_m2"]))
    scenarios = []
    for unit, inv in zip(all_units, inventory):
        if not inv["is_overdue_flag"]:
            continue
        key = unit["unit_key"]
        cause = cause_by_key.get(key, "LEGAL_PERMIT_BARRIER")
        climate = "HOT" if unit["balcony_orientation"] in {"W", "SW", "NW"} else "COOL"
        area = Decimal(unit["net_area_m2"])
        peers = [price for other, other_area, price in peer_price[
            (unit["project_key"], unit["unit_type"], unit["floor_band"], climate)]
            if other != key and abs(other_area - area) <= area * Decimal("0.10")]
        peer_spread = dec((Decimal(inv["net_price_per_m2"]) / Decimal(str(median(peers))) - 1) * 100, 2) if len(peers) >= 5 else None
        comp_prices = [c["resale_price_per_m2_vnd"] for c in rows["dim_secondary_market_comps"]
                       if c["unit_type"] == unit["unit_type"] and c["recorded_resale_date"] >= SNAP - timedelta(days=90)]
        secondary_gap = dec((Decimal(inv["net_price_per_m2"]) / Decimal(str(median(comp_prices))) - 1) * 100, 2) if comp_prices else None
        physical = 30 if Decimal(unit["distance_to_trash_room_m"]) < 3 else 0
        thermal = 40 if climate == "HOT" and Decimal(unit["west_facing_exposure_pct"]) >= Decimal("0.70") else 0
        booking = funnel_totals[key][2]
        dropoff = dec(Decimal(funnel_totals[key][3]) * 100 / booking, 2) if booking else None
        pir = dec(Decimal(inv["net_price_vnd"]) / 150_000_000, 1)
        diagnostic_id = f"DIAG-20260630-{key:05d}"
        rows["dm_unit_friction_diagnostics"].append(dict(
            diagnostic_id=diagnostic_id, snapshot_date_key=date_key(SNAP), unit_key=key,
            unit_code=unit["unit_code"], project_name="Vinhomes Smart City" if key <= 1200 else "VHSC fictional legal phase",
            zone_name=zone_labels[unit["zone_key"] - 1], unsold_days_dom=inv["unsold_days_dom"],
            price_spread_vs_peer_pct=peer_spread, ticket_size_vs_income_ratio=pir,
            physical_defect_penalty=physical, thermal_view_penalty=thermal,
            secondary_price_gap_pct=secondary_gap, funnel_dropoff_rate_pct=dropoff,
            primary_cause_code=cause, recommended_action=ACTIONS[cause],
        ))
        secondaries = []
        if cause != "LOW_SALES_INCENTIVE" and inv["base_commission_pct"] == "1.20":
            secondaries.append("LOW_SALES_INCENTIVE")
        if cause != "SECONDARY_ARBITRAGE" and secondary_gap is not None and Decimal(secondary_gap) > 15:
            secondaries.append("SECONDARY_ARBITRAGE")
        if (cause != "OVERPRICED_VS_PEER" and peer_spread is not None
                and Decimal(peer_spread) > 8 and physical == 0 and thermal == 0):
            secondaries.append("OVERPRICED_VS_PEER")
        ranked = [cause, *secondaries[:2]]
        scores = {1: ["1.000"], 2: ["0.650", "0.350"], 3: ["0.600", "0.250", "0.150"]}[len(ranked)]
        for rank, (code, score) in enumerate(zip(ranked, scores), 1):
            rows["unit_diagnostic_causes"].append(dict(
                diagnostic_id=diagnostic_id, cause_code=code, unit_key=key,
                snapshot_date_key=date_key(SNAP), severity_rank=rank,
                attribution_score=score, evidence_artifact_id=None,
            ))
        scenarios.append(dict(unit_id=unit["unit_id"], project_id="PRJ-VHSC-HN" if key <= 1200 else "PRJ-VHSC-LEGAL-MOCK",
                              diagnostic_id=diagnostic_id, expected_primary_cause=cause,
                              expected_causes=ranked))

    columns = columns_from_contract()
    for table, records in rows.items():
        if not records:
            raise AssertionError(f"No records for {table}")
        expected = set(columns[table])
        for record in records:
            if set(record) != expected:
                raise AssertionError(f"Column mismatch for {table}: {set(record) ^ expected}")
        with (OUT / f"{table}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns[table], lineterminator="\n")
            writer.writeheader()
            for record in records:
                writer.writerow({key: ("t" if value else "f") if isinstance(value, bool) else
                                 "" if value is None else value.isoformat() if isinstance(value, date) else value
                                 for key, value in record.items()})
    (OUT / "expected_scenarios.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")
    controls = {
        "sold_not_diagnosed": "VHSC-U-00001",
        "booked_not_diagnosed": "VHSC-U-00007",
        "available_dom_90_not_diagnosed": f"VHSC-U-{edge_not_overdue_key:05d}",
        "available_dom_91_diagnosed": f"VHSC-U-{edge_overdue_key:05d}",
    }
    (OUT / "negative_controls.json").write_text(json.dumps(controls, indent=2), encoding="utf-8")
    exemplars = {}
    for scenario in scenarios:
        exemplars.setdefault(scenario["expected_primary_cause"], scenario)
    eval_cases = []
    for index, (cause, scenario) in enumerate(sorted(exemplars.items()), 1):
        unit_id = scenario["unit_id"]
        eval_cases.append(dict(
            test_case_id=f"vhsc_20260630_{index:02d}", testset_id="ts_vhsc_slowmoving_20260630",
            prompt_input=f"Vì sao căn {unit_id} bán chậm tại snapshot 30/06/2026?",
            expected_intent="DIAGNOSE_SLOW_MOVING_UNIT",
            expected_sql_query=("SELECT c.cause_code FROM dw.unit_diagnostic_causes c "
                                "JOIN dw.dim_unit_master u ON u.unit_key = c.unit_key "
                                f"WHERE u.unit_id = '{unit_id}' AND c.snapshot_date_key = 20260630 "
                                "ORDER BY c.severity_rank;"),
            ground_truth_causes=scenario["expected_causes"], difficulty_level="MEDIUM",
            unit_id=unit_id, project_id=scenario["project_id"], snapshot_id="SNAP-20260630-01",
        ))
    for index, unit_id in enumerate(("VHSC-U-00001", "VHSC-U-00007", controls["available_dom_90_not_diagnosed"]), 9):
        eval_cases.append(dict(
            test_case_id=f"vhsc_20260630_{index:02d}", testset_id="ts_vhsc_slowmoving_20260630",
            prompt_input=f"Căn {unit_id} có cần chẩn đoán bán chậm tại snapshot 30/06/2026 không?",
            expected_intent="DIAGNOSE_SLOW_MOVING_UNIT",
            expected_sql_query=("SELECT c.cause_code FROM dw.unit_diagnostic_causes c "
                                "JOIN dw.dim_unit_master u ON u.unit_key = c.unit_key "
                                f"WHERE u.unit_id = '{unit_id}' AND c.snapshot_date_key = 20260630 "
                                "ORDER BY c.severity_rank;"),
            ground_truth_causes=[], difficulty_level="EDGE_CASE", unit_id=unit_id,
            project_id="PRJ-VHSC-HN", snapshot_id="SNAP-20260630-01",
        ))
    (OUT / "eval_test_cases.json").write_text(json.dumps(eval_cases, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {table: len(records) for table, records in rows.items()}
    (OUT / "row_counts.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    load_order = [
        "snapshot_manifest", "semantic_config", "dim_date", "dim_infrastructure_assets",
        "dim_project_profile", "dim_zone_master", "dim_unit_master", "dim_sales_channel",
        "dim_secondary_market_comps", "fact_market_macro_monthly", "fact_unit_price_history",
        "fact_sales_funnel_daily", "fact_unit_inventory_snapshot", "fact_sales_channel_performance",
        "dm_unit_friction_diagnostics", "unit_diagnostic_causes",
    ]
    load_lines = [
        "-- Synthetic POC data only. Run only against the dedicated vdagent_dw_dev database.",
        "BEGIN;",
        "DO $guard$ BEGIN IF current_database() <> 'vdagent_dw_dev' THEN",
        "  RAISE EXCEPTION 'Refusing to replace data in %', current_database();",
        "END IF; END $guard$;",
        "TRUNCATE " + ", ".join(f"dw.{table}" for table in reversed(load_order)) + " RESTART IDENTITY CASCADE;",
    ]
    for table in load_order:
        cols = ", ".join(columns[table])
        load_lines.append(f"COPY dw.{table} ({cols}) FROM '/tmp/vhsc_seed/{table}.csv' WITH (FORMAT csv, HEADER true);")
    load_lines += ["COMMIT;", ""]
    (ROOT / "data" / "load_vhsc_mock.sql").write_text("\n".join(load_lines), encoding="utf-8")
    print(json.dumps({"rows": counts, "primary_causes": dict(Counter(x["expected_primary_cause"] for x in scenarios))}, indent=2))


if __name__ == "__main__":
    main()
