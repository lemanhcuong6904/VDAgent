#!/usr/bin/env python3
"""
organize_pack.py — Chuẩn hóa các file CSV của từng dự án vào thư mục canonical:
warehouse/project_<key>/ và warehouse/shared/
"""

import sys
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SHARED_DIR = BASE_DIR / "shared"
SHARED_TABLES = ("snapshot_manifest", "semantic_config", "dim_date")

from verify_warehouse import EXPECTED_HEADERS


def standardize_file(src_file, dst_file, expected_cols):
    with open(src_file, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return
        header = [c.strip() for c in header]
        
        # Mapping index
        indices = []
        for col in expected_cols:
            if col in header:
                indices.append(header.index(col))
            else:
                indices.append(None)
                
        rows = []
        for r in reader:
            new_row = []
            for idx in indices:
                if idx is not None and idx < len(r):
                    new_row.append(r[idx])
                else:
                    new_row.append("")
            rows.append(new_row)

    dst_file.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(expected_cols)
        writer.writerows(rows)


def deploy_project_100():
    vhop_dir = BASE_DIR / "vhop"
    p100_dir = BASE_DIR / "project_100"
    p100_dir.mkdir(parents=True, exist_ok=True)
    SHARED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Shared tables
    for tname in SHARED_TABLES:
        src = vhop_dir / f"{tname}.csv"
        dst = SHARED_DIR / f"{tname}.csv"
        if src.exists():
            standardize_file(src, dst, EXPECTED_HEADERS[tname])
            print(f"Standardized shared: {dst.name}")

    # 2. Project 100 tables
    for tname, expected_cols in EXPECTED_HEADERS.items():
        if tname in SHARED_TABLES:
            continue
        src = vhop_dir / f"{tname}.csv"
        dst = p100_dir / f"{tname}.csv"
        if src.exists():
            standardize_file(src, dst, expected_cols)
            print(f"Standardized project_100: {dst.name}")


def deploy_project_200():
    vhsc_dir = BASE_DIR.parent / "data" / "mock" / "vhsc_20260630"
    p200_dir = BASE_DIR / "project_200"
    p200_dir.mkdir(parents=True, exist_ok=True)

    for tname, expected_cols in EXPECTED_HEADERS.items():
        if tname in SHARED_TABLES:
            continue
        src = vhsc_dir / f"{tname}.csv"
        dst = p200_dir / f"{tname}.csv"
        if src.exists():
            standardize_file(src, dst, expected_cols)
            print(f"Standardized project_200: {dst.name}")


def deploy_project_300():
    vgp_dir = BASE_DIR.parent / "data" / "VGP" / "data"
    p300_dir = BASE_DIR / "project_300"
    p300_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "dim_project_profile": "04_dim_project_profile.csv",
        "dim_zone_master": "05_dim_zone_master.csv",
        "dim_unit_master": "06_dim_unit_master.csv",
        "dim_sales_channel": "07_dim_sales_channel.csv",
        "dim_infrastructure_assets": "08_dim_infrastructure_assets.csv",
        "dim_secondary_market_comps": "12_dim_secondary_market_comps.csv",
        "fact_unit_inventory_snapshot": "09_fact_unit_inventory_snapshot.csv",
        "fact_sales_funnel_daily": "10_fact_sales_funnel_daily.csv",
        "fact_unit_price_history": "11_fact_unit_price_history.csv",
        "fact_market_macro_monthly": "13_fact_market_macro_monthly.csv",
        "fact_sales_channel_performance": "14_fact_sales_channel_performance.csv",
        "dm_unit_friction_diagnostics": "15_dm_unit_friction_diagnostics.csv",
    }

    for tname, fname in mapping.items():
        src = vgp_dir / fname
        dst = p300_dir / f"{tname}.csv"
        expected_cols = EXPECTED_HEADERS[tname]
        
        if tname == "dim_unit_master":
            # Add unit_id and ext_attributes
            with open(src, "r", encoding="utf-8-sig") as f:
                r = csv.DictReader(f)
                rows = []
                for row in r:
                    new_row = []
                    for c in expected_cols:
                        if c == "unit_id":
                            new_row.append(row["unit_code"])
                        elif c == "ext_attributes":
                            new_row.append("{}")
                        else:
                            new_row.append(row.get(c, ""))
                    rows.append(new_row)
            with open(dst, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(expected_cols)
                w.writerows(rows)
            print(f"Standardized project_300: {dst.name}")
        else:
            standardize_file(src, dst, expected_cols)
            print(f"Standardized project_300: {dst.name}")

    # Generate unit_diagnostic_causes from dm_unit_friction_diagnostics
    diag_csv = p300_dir / "dm_unit_friction_diagnostics.csv"
    causes_csv = p300_dir / "unit_diagnostic_causes.csv"
    with open(diag_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cause_rows = []
        for r in reader:
            cause_rows.append([
                r["diagnostic_id"],
                r["primary_cause_code"],
                r["unit_key"],
                r["snapshot_date_key"],
                1,
                "1.000",
                ""
            ])
    with open(causes_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(EXPECTED_HEADERS["unit_diagnostic_causes"])
        w.writerows(cause_rows)
    print(f"Standardized project_300: {causes_csv.name} ({len(cause_rows)} rows)")


if __name__ == "__main__":
    deploy_project_100()
    deploy_project_200()
    deploy_project_300()


