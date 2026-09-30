#!/usr/bin/env python3
"""
assemble_dataset.py — Gom 5 Project Packs -> 1 Central Master Dataset (16 tables)
Bao gồm bước premerge_validate và sinh dataset_manifest.json tại warehouse/dataset/
"""

import sys
import json
import csv
import hashlib
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_KEYS = [100, 200, 300, 400, 500]
SHARED_DIR = BASE_DIR / "shared"
DATASET_DIR = BASE_DIR / "dataset"

# M4 SNAPSHOT FREEZE — contract invariant: snapshot_date_key toàn bộ = 20260630.
# Một số pack (project_300 monthly, project_400 weekly) bàn giao dưới dạng
# time-series nhiều snapshot. Khi gom Master Dataset, chỉ giữ lát cắt đóng băng
# 2026-06-30 cho MỌI bảng có cột snapshot_date_key. Các bảng dùng date/time key
# khác (funnel daily, price history, macro monthly) giữ nguyên chuỗi thời gian.
SNAPSHOT_FREEZE = "20260630"

# Ensure UTF-8 output encoding on Windows terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from verify_warehouse import (
    EXPECTED_HEADERS,
    compute_sha256,
    read_csv_clean,
    validate_project_folder,
    validate_global_keys
)


def premerge_validate():
    """
    Bước 1: Kiểm tra tiền hợp nhất (Pre-Merge Sanity & Integrity Validation)
    cho 5 project packs và 3 bảng shared.
    """
    print("=" * 60)
    print("PRE-MERGE VALIDATION: KIỂM TRA TOÀN VẸN 5 PROJECT PACKS")
    print("=" * 60)

    reg_path = BASE_DIR / "id_registry.json"
    if not reg_path.exists():
        print(f"❌ Lỗi: Không tìm thấy file registry tại {reg_path}")
        return False

    with open(reg_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # 1. Kiểm tra các file shared
    print("\n[1/3] Kiểm tra Shared Dimensions & Manifest:")
    for stname in ("snapshot_manifest", "semantic_config", "dim_date"):
        csv_p = SHARED_DIR / f"{stname}.csv"
        if not csv_p.exists():
            print(f"❌ Thiếu file shared: {csv_p}")
            return False
        hdr, rows = read_csv_clean(csv_p)
        if hdr != EXPECTED_HEADERS[stname]:
            print(f"❌ Lỗi header ở file shared: {stname}.csv")
            return False
        print(f"  ✅ Shared {stname}.csv: {len(rows)} dòng PASS")

    # 2. Kiểm tra từng project pack
    print("\n[2/3] Kiểm tra hợp đồng & logic 5 Project Packs:")
    total_errors = 0
    for pkey in PROJECT_KEYS:
        p_folder = BASE_DIR / f"project_{pkey}"
        errs, warns, minfo = validate_project_folder(p_folder, pkey, registry)
        if errs:
            print(f"❌ Project {pkey} có {len(errs)} lỗi:")
            for e in errs[:5]:
                print(f"   - {e}")
            total_errors += len(errs)
        else:
            print(f"  ✅ Project {pkey} ({p_folder.name}): PASS 13/13 bảng")

    # 3. Kiểm tra PK/UK độc nhất toàn cục
    print("\n[3/3] Kiểm tra Độc nhất Khóa chính/Khóa tự nhiên (Global Primary Key Uniqueness):")
    global_errs = validate_global_keys(BASE_DIR, PROJECT_KEYS)
    if global_errs:
        print(f"❌ Phát hiện trùng lặp khóa giữa các dự án:")
        for ge in global_errs:
            print(f"   - {ge}")
        total_errors += len(global_errs)
    else:
        print("  ✅ Mọi PK/UK của 13 bảng đều duy nhất tuyệt đối khi hợp nhất toàn cục!")

    if total_errors > 0:
        print(f"\n❌ PRE-MERGE VALIDATION KHÔNG ĐẠT (Có {total_errors} lỗi cần xử lý).")
        return False

    print("\n✅ PRE-MERGE VALIDATION THÀNH CÔNG 100%! ĐỦ ĐIỀU KIỆN GOM DATASET.")
    return True


def assemble_dataset():
    """
    Bước 2: Gom 13 bảng từ 5 project packs + 3 bảng shared thành 1 Central Master Dataset.
    Thư mục đầu ra: warehouse/dataset/
    """
    print("\n" + "=" * 60)
    print("ASSEMBLING CENTRAL MASTER DATASET: 5 PACKS -> 1 DATASET")
    print("=" * 60)

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    table_stats = {}

    # 1. Sao chép 3 bảng Shared
    shared_tables = ("snapshot_manifest", "semantic_config", "dim_date")
    for stname in shared_tables:
        src = SHARED_DIR / f"{stname}.csv"
        dst = DATASET_DIR / f"{stname}.csv"
        header, rows = read_csv_clean(src)

        with open(dst, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

        sha = compute_sha256(dst)
        table_stats[stname] = {
            "rows": len(rows),
            "sha256": sha,
            "table_type": "shared"
        }
        print(f"  📦 [Shared] {stname}.csv: {len(rows)} dòng -> {dst.name}")

    # 2. Nối 13 bảng dự án từ project_100 đến project_500
    project_tables = [t for t in EXPECTED_HEADERS.keys() if t not in shared_tables]
    for ptname in project_tables:
        expected_cols = EXPECTED_HEADERS[ptname]
        # Bảng có cột snapshot_date_key thì áp dụng đóng băng 2026-06-30.
        snap_idx = expected_cols.index("snapshot_date_key") \
            if "snapshot_date_key" in expected_cols else None
        combined_rows = []
        dropped_offsnapshot = 0

        for pkey in PROJECT_KEYS:
            p_file = BASE_DIR / f"project_{pkey}" / f"{ptname}.csv"
            if not p_file.exists():
                print(f"⚠️ Cảnh báo: Thiếu file {ptname}.csv ở project_{pkey}")
                continue

            header, rows = read_csv_clean(p_file)
            if header != expected_cols:
                print(f"⚠️ Cảnh báo: Lệch header ở project_{pkey}/{ptname}.csv")
            if snap_idx is not None:
                kept = [r for r in rows if len(r) > snap_idx and r[snap_idx] == SNAPSHOT_FREEZE]
                dropped_offsnapshot += len(rows) - len(kept)
                rows = kept
            combined_rows.extend(rows)

        dst = DATASET_DIR / f"{ptname}.csv"
        with open(dst, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(expected_cols)
            writer.writerows(combined_rows)

        sha = compute_sha256(dst)
        table_stats[ptname] = {
            "rows": len(combined_rows),
            "sha256": sha,
            "table_type": "master_concatenated",
        }
        if snap_idx is not None:
            table_stats[ptname]["snapshot_frozen"] = SNAPSHOT_FREEZE
            table_stats[ptname]["dropped_offsnapshot_rows"] = dropped_offsnapshot
            print(f"  📦 [Master] {ptname}.csv: {len(combined_rows)} dòng "
                  f"(đóng băng {SNAPSHOT_FREEZE}, loại {dropped_offsnapshot} dòng off-snapshot) -> {dst.name}")
        else:
            print(f"  📦 [Master] {ptname}.csv: {len(combined_rows)} dòng (tổng hợp từ 5 projects) -> {dst.name}")

    # 3. Sinh file dataset_manifest.json
    manifest_data = {
        "dataset_id": "vdagent_dw_re",
        "dataset_name": "Central Data Warehouse VDAgent Master Dataset",
        "dataset_version": "3.1.0",
        "snapshot_id": "SNAP-20260630-01",
        "snapshot_date": "2026-06-30",
        "snapshot_frozen_date_key": SNAPSHOT_FREEZE,
        "assembled_at": datetime.now().isoformat(),
        "projects_assembled": PROJECT_KEYS,
        "total_tables": len(table_stats),
        "tables": table_stats
    }

    manifest_path = DATASET_DIR / "dataset_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    print(f"\n  📄 Sinh dataset manifest: dataset_manifest.json")
    print("=" * 60)
    print("TỔNG KẾT: QUY TRÌNH ASSEMBLE DATASET HOÀN TẤT THÀNH CÔNG!")
    print(f"Thư mục Master Dataset: {DATASET_DIR}")
    print("=" * 60)
    return True


if __name__ == "__main__":
    if not premerge_validate():
        sys.exit(1)
    if not assemble_dataset():
        sys.exit(1)
