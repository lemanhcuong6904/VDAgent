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


if __name__ == "__main__":
    deploy_project_100()
