#!/usr/bin/env python3
"""M4 ACCEPTANCE GATES — chứng minh trên warehouse/dataset (Master Dataset đã đóng băng).

Chạy: python warehouse/tests/m4_verify_gates.py
Thoát code != 0 nếu bất kỳ gate nào FAIL. In bằng chứng đếm được cho từng gate.

Gate 1: Σ attribution_score = 1.000 cho MỖI diagnostic_id (không sai số > 1e-9).
Gate 2: Phủ đủ 8/8 core cause toàn kho (gồm LEGAL_PERMIT_BARRIER).
Gate 3: 0 UNEXPLAINED — mọi unit AVAILABLE & DOM>threshold tại 20260630 có diagnostic;
        không có primary_cause_code == 'UNEXPLAINED'; mart<->bridge nhất quán.
Gate 4: snapshot_date_key toàn bộ = 20260630 (4 bảng có cột này); version 3.1.0;
        FK Mart/Bridge -> dim_unit_master / dim_date / mart hợp lệ.
"""
import csv, json, sys, collections
from pathlib import Path
from decimal import Decimal

DS = Path(__file__).resolve().parents[1] / "dataset"
SHARED = Path(__file__).resolve().parents[1] / "shared"
FROZEN = "20260630"
CORE_8 = {
    "LEGAL_PERMIT_BARRIER", "SEVERE_PHYSICAL_DEFECT", "EXTREME_THERMAL_EXPOSURE",
    "SECONDARY_ARBITRAGE", "LUMP_SUM_TICKET_BARRIER", "OVERPRICED_VS_PEER",
    "LOW_SALES_INCENTIVE", "DEEP_FUNNEL_DROP_OFF",
}
SNAPSHOT_TABLES = ["fact_unit_inventory_snapshot", "fact_sales_channel_performance",
                   "dm_unit_friction_diagnostics", "unit_diagnostic_causes"]

def read(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

results = []
def gate(name, ok, detail):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

scfg = {r["config_key"]: r["config_value"] for r in read(SHARED / "semantic_config.csv")}
OVERDUE = int(scfg.get("overdue_threshold_days", "90"))

units = read(DS / "dim_unit_master.csv")
dim = read(DS / "dim_date.csv")
inv = read(DS / "fact_unit_inventory_snapshot.csv")
mart = read(DS / "dm_unit_friction_diagnostics.csv")
bridge = read(DS / "unit_diagnostic_causes.csv")
manifest = json.loads((DS / "dataset_manifest.json").read_text(encoding="utf-8"))
snap_manifest = read(DS / "snapshot_manifest.csv")[0]

unit_keys = {u["unit_key"] for u in units}
date_keys = {d["date_key"] for d in dim}

print(f"context: overdue_threshold_days={OVERDUE}, dim_unit_master={len(units)}, "
      f"inventory={len(inv)}, mart={len(mart)}, bridge={len(bridge)}\n")

# ---- Gate 1: attribution sum = 1.000 per diagnostic ----
asum = collections.defaultdict(Decimal)
for r in bridge:
    asum[r["diagnostic_id"]] += Decimal(r["attribution_score"])
bad_attr = {k: str(v) for k, v in asum.items() if abs(v - Decimal("1")) > Decimal("1e-9")}
gate("G1 attribution=1.000",
     len(bad_attr) == 0,
     f"{len(asum)} diagnostic_id, {len(bad_attr)} lệch != 1.000" +
     (f" ex={list(bad_attr.items())[:3]}" if bad_attr else ""))

# ---- Gate 2: 8/8 core cause coverage ----
causes_bridge = {r["cause_code"] for r in bridge}
causes_primary = {r["primary_cause_code"] for r in mart}
missing = CORE_8 - causes_bridge
extra = (causes_bridge | causes_primary) - CORE_8
gate("G2 8/8 core cause",
     len(missing) == 0,
     f"core phủ {len(CORE_8 & causes_bridge)}/8" +
     (f", THIẾU {sorted(missing)}" if missing else f"; fallback ngoài core={sorted(extra)}"))

# ---- Gate 3: 0 UNEXPLAINED ----
eligible = {r["unit_key"] for r in inv
            if r["inventory_status"] == "AVAILABLE" and int(r["unsold_days_dom"]) > OVERDUE}
diagnosed_units = {r["unit_key"] for r in mart}
unexplained_units = eligible - diagnosed_units
literal_unexpl = [r["diagnostic_id"] for r in mart if r["primary_cause_code"] == "UNEXPLAINED"]
mart_ids = {r["diagnostic_id"] for r in mart}
bridge_ids = {r["diagnostic_id"] for r in bridge}
mart_no_bridge = mart_ids - bridge_ids
bridge_no_mart = bridge_ids - mart_ids
g3_ok = (not unexplained_units and not literal_unexpl and not mart_no_bridge and not bridge_no_mart)
gate("G3 0 UNEXPLAINED",
     g3_ok,
     f"eligible={len(eligible)} diagnosed={len(diagnosed_units)} unexplained={len(unexplained_units)} "
     f"literal_UNEXPLAINED={len(literal_unexpl)} mart-without-bridge={len(mart_no_bridge)} "
     f"bridge-without-mart={len(bridge_no_mart)}")
if unexplained_units:
    print(f"      sample unexplained: {sorted(unexplained_units)[:8]}")

# ---- Gate 4: snapshot freeze + version + FK ----
snap_problems = {}
for t in SNAPSHOT_TABLES:
    rows = read(DS / f"{t}.csv")
    vals = {r["snapshot_date_key"] for r in rows}
    if vals != {FROZEN}:
        snap_problems[t] = sorted(vals)
ver_ok = (snap_manifest["dataset_version"] == "3.1.0"
          and snap_manifest["semantic_version"] == "3.1.0"
          and manifest["dataset_version"] == "3.1.0")
# FK checks
fk_mart_unit = {r["unit_key"] for r in mart} - unit_keys
fk_bridge_unit = {r["unit_key"] for r in bridge} - unit_keys
fk_mart_date = {r["snapshot_date_key"] for r in mart} - date_keys
fk_bridge_diag = bridge_ids - mart_ids  # every bridge row must point to an existing mart diagnostic
g4_ok = (not snap_problems and ver_ok and not fk_mart_unit
         and not fk_bridge_unit and not fk_mart_date and not fk_bridge_diag)
detail = (f"snapshot!=20260630 tables={snap_problems or 'none'}; version3.1.0={ver_ok}; "
          f"FK mart.unit∉dim={len(fk_mart_unit)} bridge.unit∉dim={len(fk_bridge_unit)} "
          f"mart.snapshot∉dim_date={len(fk_mart_date)} bridge.diag∉mart={len(fk_bridge_diag)}")
gate("G4 snapshot/version/FK", g4_ok, detail)

print("\n" + "=" * 60)
all_ok = all(ok for _, ok, _ in results)
print("M4 ACCEPTANCE GATES: " + ("ALL PASS ✅" if all_ok else "FAIL ❌"))
print("=" * 60)
sys.exit(0 if all_ok else 1)
