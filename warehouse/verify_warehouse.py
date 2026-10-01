#!/usr/bin/env python3
"""
verify_warehouse.py — Quality Gate cho Central Data Warehouse VDAgent
Kiểm tra tính toàn vẹn 16 bảng theo schema_final_16_tables.sql,
id_registry.json v3.1.1, SNAPSHOT_RULES.md, và Plan_Merge_4_Branches_To_DATA.md.
"""

import os
import sys
import json
import csv
import hashlib
from pathlib import Path
from collections import defaultdict

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

EXPECTED_HEADERS = {
    "snapshot_manifest": [
        "snapshot_id", "dataset_id", "dataset_version", "semantic_version",
        "snapshot_date", "timezone", "currency", "price_basis", "area_basis", "source_system"
    ],
    "semantic_config": [
        "config_key", "config_value", "value_type", "semantic_version",
        "approval_status", "description"
    ],
    "dim_date": [
        "date_key", "full_date", "year", "quarter", "month", "day_of_month",
        "is_weekend", "fiscal_quarter"
    ],
    "dim_project_profile": [
        "project_key", "project_id", "project_name", "market_id", "market_name",
        "province_city", "district", "developer_name", "developer_tier",
        "developer_origin", "segment", "construction_status", "construction_progress_pct",
        "is_sales_permit_issued", "is_bank_guarantee_issued", "max_foreign_quota_exceeded",
        "primary_infra_id", "distance_to_primary_infra_m", "partner_bank_name",
        "expected_handover_date"
    ],
    "dim_zone_master": [
        "zone_key", "zone_id", "project_key", "zone_name", "zone_type",
        "total_floors", "basement_floors", "units_per_floor", "passenger_elevators",
        "elevator_ratio", "handover_standard"
    ],
    "dim_unit_master": [
        "unit_key", "unit_id", "unit_code", "project_key", "zone_key", "unit_type",
        "bedroom_count", "bathroom_count", "net_area_m2", "gross_area_m2",
        "floor_number", "floor_band", "balcony_orientation", "door_orientation",
        "view_primary_type", "is_corner_unit", "efficiency_ratio",
        "distance_to_trash_room_m", "is_adjacent_elevator", "dark_bedroom_count",
        "west_facing_exposure_pct", "view_obstruction_distance_m",
        "taboo_view_type", "is_taboo_floor", "ext_attributes"
    ],
    "dim_sales_channel": [
        "channel_key", "channel_id", "channel_name", "channel_tier", "active_brokers_count"
    ],
    "dim_infrastructure_assets": [
        "infra_key", "infra_id", "infra_name", "infra_type", "lifecycle_stage",
        "construction_progress_pct", "original_completion_year", "revised_completion_year"
    ],
    "dim_secondary_market_comps": [
        "comp_id", "project_id", "unit_type", "floor_band", "balcony_orientation",
        "recorded_resale_date", "resale_price_per_m2_vnd", "pink_book_status"
    ],
    "fact_unit_inventory_snapshot": [
        "snapshot_date_key", "unit_key", "project_key", "zone_key", "channel_key",
        "launch_batch_id", "release_date", "inventory_status", "sold_date",
        "unsold_days_dom", "is_overdue_flag", "asking_price_vnd", "discount_pct",
        "concession_value_vnd", "net_price_vnd", "asking_price_per_m2",
        "net_price_per_m2", "subsidy_duration_mo", "principal_grace_mo",
        "base_commission_pct", "spiff_bonus_vnd", "is_exclusive_lock"
    ],
    "fact_sales_funnel_daily": [
        "funnel_event_id", "date_key", "unit_key", "web_listing_views",
        "inquiry_leads_count", "site_visits_count", "booking_reservations",
        "booking_cancellations", "cancellation_reason"
    ],
    "fact_unit_price_history": [
        "price_event_id", "unit_key", "effective_date_key", "old_asking_price_vnd",
        "new_asking_price_vnd", "price_change_pct", "change_reason"
    ],
    "fact_market_macro_monthly": [
        "macro_record_id", "date_key", "market_id", "segment",
        "floating_mortgage_rate_pct", "months_of_inventory_moi",
        "absorption_rate_pct", "median_household_income_vnd",
        "macro_price_to_income_ratio"
    ],
    "fact_sales_channel_performance": [
        "snapshot_date_key", "channel_key", "project_key", "assigned_units_count",
        "sold_units_count", "absorption_rate_pct", "avg_days_to_sell",
        "locked_inventory_over_90d"
    ],
    "dm_unit_friction_diagnostics": [
        "diagnostic_id", "snapshot_date_key", "unit_key", "unit_code",
        "project_name", "zone_name", "unsold_days_dom", "price_spread_vs_peer_pct",
        "ticket_size_vs_income_ratio", "physical_defect_penalty",
        "thermal_view_penalty", "secondary_price_gap_pct", "funnel_dropoff_rate_pct",
        "primary_cause_code", "recommended_action"
    ],
    "unit_diagnostic_causes": [
        "diagnostic_id", "cause_code", "unit_key", "snapshot_date_key",
        "severity_rank", "attribution_score", "evidence_artifact_id"
    ]
}


# PK and UK constraints from schema_final_16_tables.sql for project-scoped CSVs.
GLOBAL_UNIQUE_KEYS = {
    "dim_project_profile": [("project_key",), ("project_id",)],
    "dim_zone_master": [("zone_key",), ("zone_id",)],
    "dim_unit_master": [("unit_key",), ("unit_id",)],
    "dim_sales_channel": [("channel_key",), ("channel_id",)],
    "dim_infrastructure_assets": [("infra_key",), ("infra_id",)],
    "dim_secondary_market_comps": [("comp_id",)],
    "fact_unit_inventory_snapshot": [("snapshot_date_key", "unit_key")],
    "fact_sales_funnel_daily": [("funnel_event_id",)],
    "fact_unit_price_history": [("price_event_id",)],
    "fact_market_macro_monthly": [("macro_record_id",)],
    "fact_sales_channel_performance": [("snapshot_date_key", "channel_key", "project_key")],
    "dm_unit_friction_diagnostics": [("diagnostic_id",)],
    "unit_diagnostic_causes": [("diagnostic_id", "cause_code")],
}


def validate_global_keys(base_dir, project_keys, constraints=GLOBAL_UNIQUE_KEYS):
    """Check PK/UK collisions across packs before their rows enter shared tables."""
    errors = []
    for table_name, key_columns_list in constraints.items():
        seen = {columns: {} for columns in key_columns_list}
        collisions = {columns: 0 for columns in key_columns_list}
        examples = {}
        for project_key in project_keys:
            csv_path = Path(base_dir) / f"project_{project_key}" / f"{table_name}.csv"
            if not csv_path.exists():
                errors.append(f"Missing global-key input: {csv_path}")
                continue
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                missing = [col for cols in key_columns_list for col in cols if col not in (reader.fieldnames or ())]
                if missing:
                    errors.append(f"{csv_path}: missing key columns {sorted(set(missing))}")
                    continue
                for row in reader:
                    for columns in key_columns_list:
                        key = tuple(row[column] for column in columns)
                        if not all(key):
                            errors.append(f"{csv_path}: null/empty key {columns}")
                            continue
                        if key in seen[columns]:
                            first_project = seen[columns][key]
                            collisions[columns] += 1
                            examples.setdefault((columns, key), (first_project, project_key))
                        else:
                            seen[columns][key] = project_key
        for columns, count in collisions.items():
            if count:
                key, owners = next(
                    (key, owners) for (constraint, key), owners in examples.items()
                    if constraint == columns
                )
                errors.append(
                    f"{table_name}.{'+'.join(columns)}: {count} duplicate rows in combined dataset; "
                    f"example {key} in projects {owners[0]} and {owners[1]}"
                )
    return errors


def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_csv_clean(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return [], []
        # strip whitespace
        header = [col.strip() for col in header]
        rows = [row for row in reader]
    return header, rows


def validate_project_folder(folder_path, project_key, registry):
    errors = []
    warnings = []
    manifest_info = {}

    p_spec = None
    for p in registry.get("projects", []):
        if p["project_key"] == project_key:
            p_spec = p
            break
    if not p_spec:
        errors.append(f"Không tìm thấy cấu hình cho project_key={project_key} trong id_registry.json")
        return errors, warnings, manifest_info

    bands = registry.get("conformed_dims", {})
    chan_band = bands.get("channel_key", {}).get("bands", {}).get(str(project_key), [0, 0])
    infra_band = bands.get("infra_key", {}).get("bands", {}).get(str(project_key), [0, 0])

    folder = Path(folder_path)
    if not folder.exists():
        errors.append(f"Thư mục không tồn tại: {folder}")
        return errors, warnings, manifest_info

    # 13 project-specific tables
    project_tables = [t for t in EXPECTED_HEADERS.keys() if t not in ("snapshot_manifest", "semantic_config", "dim_date")]

    unit_keys_seen = set()
    zone_keys_seen = set()
    channel_keys_seen = set()
    infra_keys_seen = set()
    diagnostics_seen = set()

    for tname in project_tables:
        csv_file = folder / f"{tname}.csv"
        if not csv_file.exists():
            errors.append(f"Thiếu file: {csv_file}")
            continue

        sha = compute_sha256(csv_file)
        header, rows = read_csv_clean(csv_file)
        manifest_info[tname] = {"rows": len(rows), "sha256": sha}

        expected = EXPECTED_HEADERS[tname]
        if header != expected:
            errors.append(f"Header sai ở {tname}.csv:\n  Có:  {header}\n  Cần: {expected}")

        # Table-specific checks
        if tname == "dim_project_profile":
            for row in rows:
                r_dict = dict(zip(header, row))
                pkey = int(r_dict["project_key"])
                pid = r_dict["project_id"]
                if pkey != project_key:
                    errors.append(f"dim_project_profile: project_key {pkey} != {project_key}")
                if pid != p_spec["project_id"]:
                    errors.append(f"dim_project_profile: project_id {pid} != {p_spec['project_id']}")

        elif tname == "dim_zone_master":
            for row in rows:
                r_dict = dict(zip(header, row))
                zkey = int(r_dict["zone_key"])
                zone_keys_seen.add(zkey)
                if not (p_spec["zone_key_min"] <= zkey <= p_spec["zone_key_max"]):
                    errors.append(f"zone_key {zkey} nằm ngoài dải [{p_spec['zone_key_min']}, {p_spec['zone_key_max']}]")

        elif tname == "dim_unit_master":
            for row in rows:
                r_dict = dict(zip(header, row))
                ukey = int(r_dict["unit_key"])
                unit_keys_seen.add(ukey)
                if not (p_spec["unit_key_min"] <= ukey <= p_spec["unit_key_max"]):
                    errors.append(f"unit_key {ukey} ngoài dải [{p_spec['unit_key_min']}, {p_spec['unit_key_max']}]")
                ucode = r_dict["unit_code"]
                # prefix check (unit_code or unit_id)
                uid = r_dict["unit_id"]
                if not (ucode.startswith(p_spec["unit_code_prefix"]) or uid.startswith(f"U-{p_spec['unit_code_prefix']}") or uid.startswith(p_spec["unit_code_prefix"])):
                    warnings.append(f"unit_id/unit_code ({uid} / {ucode}) không chứa prefix {p_spec['unit_code_prefix']}")

        elif tname == "dim_sales_channel":
            for row in rows:
                r_dict = dict(zip(header, row))
                ckey = int(r_dict["channel_key"])
                channel_keys_seen.add(ckey)
                if not (chan_band[0] <= ckey <= chan_band[1]):
                    errors.append(f"channel_key {ckey} ngoài dải [{chan_band[0]}, {chan_band[1]}]")

        elif tname == "dim_infrastructure_assets":
            for row in rows:
                r_dict = dict(zip(header, row))
                ikey = int(r_dict["infra_key"])
                infra_keys_seen.add(ikey)
                if not (infra_band[0] <= ikey <= infra_band[1]):
                    errors.append(f"infra_key {ikey} ngoài dải [{infra_band[0]}, {infra_band[1]}]")

        elif tname == "fact_unit_inventory_snapshot":
            for row in rows:
                r_dict = dict(zip(header, row))
                asking = float(r_dict["asking_price_vnd"])
                net = float(r_dict["net_price_vnd"])
                if net > asking:
                    errors.append(f"fact_unit_inventory_snapshot: net_price ({net}) > asking_price ({asking}) tại unit_key={r_dict['unit_key']}")
                status = r_dict["inventory_status"]
                sold_date = r_dict["sold_date"].strip()
                rel_date = r_dict["release_date"].strip()
                if status == "SOLD":
                    if not sold_date or sold_date < rel_date:
                        errors.append(f"SOLD unit {r_dict['unit_key']} có sold_date hợp lệ >= release_date ({sold_date} < {rel_date})")
                elif status in ("AVAILABLE", "BOOKED"):
                    if sold_date:
                        errors.append(f"Căn {status} {r_dict['unit_key']} nhưng sold_date không rỗng: {sold_date}")

        elif tname == "fact_sales_funnel_daily":
            for row in rows:
                r_dict = dict(zip(header, row))
                bk_res = int(r_dict["booking_reservations"])
                bk_can = int(r_dict["booking_cancellations"])
                if bk_can > bk_res:
                    errors.append(f"Funnel error: booking_cancellations ({bk_can}) > booking_reservations ({bk_res}) tại event_id={r_dict['funnel_event_id']}")

        elif tname == "dm_unit_friction_diagnostics":
            for row in rows:
                r_dict = dict(zip(header, row))
                diag_id = r_dict["diagnostic_id"]
                diagnostics_seen.add(diag_id)
                cause = r_dict["primary_cause_code"]
                if cause == "UNEXPLAINED":
                    errors.append(f"Diagnostic error: tồn tại UNEXPLAINED tại diagnostic_id={diag_id}")

        elif tname == "unit_diagnostic_causes":
            attribution_sums = defaultdict(float)
            for row in rows:
                r_dict = dict(zip(header, row))
                diag_id = r_dict["diagnostic_id"]
                score = float(r_dict["attribution_score"])
                attribution_sums[diag_id] += score
            for diag_id, total in attribution_sums.items():
                if abs(total - 1.0) > 0.001:
                    errors.append(f"Bridge attribution sum != 1.000 (total={total:.4f}) tại diagnostic_id={diag_id}")

    return errors, warnings, manifest_info


def main():
    print("=" * 60)
    print("QUALITY GATE: CENTRAL DATA WAREHOUSE VALIDATION")
    print("=" * 60)

    reg_path = BASE_DIR / "id_registry.json"
    if not reg_path.exists():
        print(f"LỖI: Không tìm thấy {reg_path}")
        sys.exit(1)

    with open(reg_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # 1. Shared tables check
    shared_dir = BASE_DIR / "shared"
    if shared_dir.exists():
        print("\n[1] Kiểm tra Shared Dimensions & Manifest:")
        for tname in ("snapshot_manifest", "semantic_config", "dim_date"):
            csv_path = shared_dir / f"{tname}.csv"
            if not csv_path.exists():
                print(f"  - THIẾU: {csv_path}")
            else:
                hdr, rows = read_csv_clean(csv_path)
                exp = EXPECTED_HEADERS[tname]
                if hdr == exp:
                    print(f"  - PASS: {tname}.csv ({len(rows)} dòng, SHA: {compute_sha256(csv_path)[:12]}...)")
                else:
                    print(f"  - FAIL HEADER: {tname}.csv")

    # 2. Check each project directory present
    print("\n[2] Kiểm tra từng Project Data Pack:")
    all_projects_seen = {}
    total_errors = 0

    # Folders to check: project_100, project_200, project_300, project_400, project_500, or vhop
    for p_spec in registry["projects"]:
        pkey = p_spec["project_key"]
        pname = p_spec["project_name"]
        
        # Check standard folder project_<key> or fallback
        folder = BASE_DIR / f"project_{pkey}"
        if not folder.exists() and pkey == 100 and (BASE_DIR / "vhop").exists():
            folder = BASE_DIR / "vhop"

        if not folder.exists():
            print(f"  - Project {pkey} ({pname}): Chưa tích hợp (thư mục {folder.name} chưa có)")
            continue

        print(f"\n  --- Project {pkey}: {pname} (Thư mục: {folder.name}) ---")
        errs, warns, minfo = validate_project_folder(folder, pkey, registry)
        if errs:
            print(f"  ❌ PHÁT HIỆN {len(errs)} LỖI:")
            for e in errs[:10]:
                print(f"     - {e}")
            if len(errs) > 10:
                print(f"     ... và {len(errs) - 10} lỗi khác")
            total_errors += len(errs)
        else:
            print(f"  ✅ Tất cả 13 bảng dự án PASS kiểm tra contract & logic!")
            for tname, info in minfo.items():
                print(f"     • {tname}: {info['rows']} dòng")

        if warns:
            print(f"  ⚠️ Cảnh báo ({len(warns)}):")
            for w in warns[:3]:
                print(f"     - {w}")

    print("\n[3] Kiểm tra PK/UK toàn cục trên 5 project:")
    global_errors = validate_global_keys(
        BASE_DIR, [project["project_key"] for project in registry["projects"]]
    )
    if global_errors:
        for error in global_errors:
            print(f"  - FAIL: {error}")
        total_errors += len(global_errors)
    else:
        print("  - PASS: mọi PK/UK của 13 bảng project đều duy nhất khi hợp nhất")

    # 4. Check assembled Central Master Dataset if present
    ds_dir = BASE_DIR / "dataset"
    if ds_dir.exists():
        print("\n[4] Kiểm tra Central Master Dataset (warehouse/dataset):")
        ds_manifest = ds_dir / "dataset_manifest.json"
        if ds_manifest.exists():
            print("  - PASS: dataset_manifest.json tồn tại")
        else:
            print("  - FAIL: Thiếu dataset_manifest.json")
            total_errors += 1

        ds_missing = []
        for tname, exp_cols in EXPECTED_HEADERS.items():
            t_file = ds_dir / f"{tname}.csv"
            if not t_file.exists():
                ds_missing.append(f"{tname}.csv")
            else:
                hdr, rows = read_csv_clean(t_file)
                if hdr != exp_cols:
                    print(f"  - FAIL HEADER ở dataset/{tname}.csv")
                    total_errors += 1

        if ds_missing:
            print(f"  - FAIL: Thiếu {len(ds_missing)} bảng ở dataset/: {', '.join(ds_missing)}")
            total_errors += len(ds_missing)
        else:
            print("  - PASS: Đủ 16 bảng Master Dataset với header chuẩn 100%")

    print("\n" + "=" * 60)
    if total_errors == 0:
        print("TỔNG KẾT: TẤT CẢ DỮ LIỆU ĐÃ TÍCH HỢP ĐẠT QUALITY GATE!")
    else:
        print(f"TỔNG KẾT: CÓ {total_errors} LỖI CẦN XỬ LÝ.")
    print("=" * 60)
    return total_errors


if __name__ == "__main__":
    sys.exit(main())

