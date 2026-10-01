#!/usr/bin/env python3
"""Dựng bộ artifact nạp Postgres cho Central Master Dataset (backup bàn giao team khác).

Sinh vào warehouse/backup/_stage/:
  - 16 CSV đã chuẩn hoá để nạp được vào DDL nghiêm ngặt (schema `gold`):
      * ép cột INT bị format float "N.0" -> "N" (bug định dạng, không đổi ngữ nghĩa)
      * dim_date mở rộng phủ đủ mọi date_key mà fact tham chiếu (2025-01-01..2026-12-31)
  - schema_backup.sql: DDL 16 bảng, nới 2 CHECK enum cho giá trị thực của VGP
      (unit_type += DUPLEX, view_primary_type += INTERNAL_COURT)
  - load_pg.sql: nạp theo đúng thứ tự FK (mart/bridge sau cùng)
Không sửa dataset canonical; mọi sai lệch được ghi ở README.
"""
import csv, re, datetime as dt
from pathlib import Path

WH = Path(__file__).resolve().parents[1]
DS = WH / "dataset"
STAGE = WH / "backup" / "_stage"
STAGE.mkdir(parents=True, exist_ok=True)

INT_COLS = {
 "dim_zone_master": ["total_floors","basement_floors","units_per_floor","passenger_elevators"],
 "dim_infrastructure_assets": ["original_completion_year","revised_completion_year"],
 "fact_unit_inventory_snapshot": ["spiff_bonus_vnd"],
 "fact_sales_channel_performance": ["avg_days_to_sell"],
 "dm_unit_friction_diagnostics": ["physical_defect_penalty","thermal_view_penalty"],
}
FLOAT_INT = re.compile(r"^-?\d+\.0+$")
TABLES = [
 "snapshot_manifest","semantic_config","dim_date","dim_project_profile","dim_zone_master",
 "dim_unit_master","dim_sales_channel","dim_infrastructure_assets","dim_secondary_market_comps",
 "fact_unit_inventory_snapshot","fact_sales_funnel_daily","fact_unit_price_history",
 "fact_market_macro_monthly","fact_sales_channel_performance",
 "dm_unit_friction_diagnostics","unit_diagnostic_causes",
]

def coerce(v):
    return v[:v.index(".")] if FLOAT_INT.match(v or "") else v

for t in TABLES:
    with open(DS / f"{t}.csv", encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f); hdr = next(rd); rows = list(rd)
    ints = INT_COLS.get(t, [])
    idxs = [hdr.index(c) for c in ints if c in hdr]
    with open(STAGE / f"{t}.csv", "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f); wr.writerow(hdr)
        for r in rows:
            for i in idxs:
                if i < len(r):
                    r[i] = coerce(r[i])
            wr.writerow(r)

# dim_date phủ đủ range: 2025-01-01 .. 2026-12-31 (superset mọi date_key fact dùng)
start, end = dt.date(2025, 1, 1), dt.date(2026, 12, 31)
with open(STAGE / "dim_date.csv", "w", encoding="utf-8", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["date_key","full_date","year","quarter","month","day_of_month","is_weekend","fiscal_quarter"])
    d = start
    while d <= end:
        q = (d.month - 1) // 3 + 1
        wr.writerow([d.strftime("%Y%m%d"), d.isoformat(), d.year, q, d.month, d.day,
                     "True" if d.weekday() >= 5 else "False", f"{d.year}-Q{q}"])
        d += dt.timedelta(days=1)

# DDL nới 2 enum
ddl = (WH / "schema_final_16_tables.sql").read_text(encoding="utf-8")
ddl = ddl.replace("IN ('STUDIO','1PN','2PN','3PN','4PN','PENTHOUSE')",
                  "IN ('STUDIO','1PN','2PN','3PN','4PN','PENTHOUSE','DUPLEX')")
ddl = ddl.replace("IN ('RIVER','PARK','POOL','CITY_OPEN','OBSTRUCTED')",
                  "IN ('RIVER','PARK','POOL','CITY_OPEN','OBSTRUCTED','INTERNAL_COURT')")
# Villa (LOW_RISE_VILLA của VGP) không có units_per_floor/elevator -> cho phép NULL.
ddl = ddl.replace("units_per_floor      SMALLINT     NOT NULL,", "units_per_floor      SMALLINT,")
ddl = ddl.replace("passenger_elevators  SMALLINT     NOT NULL,", "passenger_elevators  SMALLINT,")
ddl = ddl.replace("elevator_ratio       DECIMAL(4,1) NOT NULL,", "elevator_ratio       DECIMAL(4,1),")
# VGP ghi recommended_action dạng mô tả dài (tới ~118 ký tự) -> nới VARCHAR(64)->256.
ddl = re.sub(r"recommended_action(\s+)VARCHAR\(64\)", r"recommended_action\1VARCHAR(256)", ddl)
(STAGE / "schema_backup.sql").write_text(ddl, encoding="utf-8")

# load_pg.sql — thứ tự FK, mart/bridge sau cùng
order = TABLES  # đã đúng thứ tự phụ thuộc
lines = ["SET search_path TO gold, public;"]
for t in order:
    lines.append(f"\\copy {t} FROM '{t}.csv' WITH (FORMAT csv, HEADER true)")
(STAGE / "load_pg.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")

print("stage ready ->", STAGE)
for t in TABLES:
    print(f"  {t}.csv")
print("  schema_backup.sql, load_pg.sql")
