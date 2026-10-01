#!/usr/bin/env python3
"""M4 gate feasibility check on frozen (snapshot_date_key=20260630) per-pack data.

Reads warehouse/project_100..500 + shared/semantic_config, applies the freeze,
and reports the 4 M4 acceptance gates BEFORE re-assembly. Does not write anything.
"""
import csv, json, collections, sys
from pathlib import Path
from decimal import Decimal

WH = Path(__file__).resolve().parents[1]
PROJECTS = [100, 200, 300, 400, 500]
FROZEN = "20260630"
CORE_8 = {
    "LEGAL_PERMIT_BARRIER", "SEVERE_PHYSICAL_DEFECT", "EXTREME_THERMAL_EXPOSURE",
    "SECONDARY_ARBITRAGE", "LUMP_SUM_TICKET_BARRIER", "OVERPRICED_VS_PEER",
    "LOW_SALES_INCENTIVE", "DEEP_FUNNEL_DROP_OFF",
}

def read(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

# overdue threshold from shared semantic_config
scfg = {r["config_key"]: r["config_value"] for r in read(WH / "shared" / "semantic_config.csv")}
OVERDUE = int(scfg.get("overdue_threshold_days", "90"))
print(f"overdue_threshold_days = {OVERDUE}  (eligible = AVAILABLE & unsold_days_dom > {OVERDUE})")
print(f"snapshot freeze = {FROZEN}\n")

tot_elig = tot_diag = tot_unexpl = 0
attr_violations = []
causes_all = set()
snap_leak = collections.Counter()
diag_ids_global = collections.Counter()

for pk in PROJECTS:
    d = WH / f"project_{pk}"
    inv = read(d / "fact_unit_inventory_snapshot.csv")
    diag = read(d / "dm_unit_friction_diagnostics.csv")
    bridge = read(d / "unit_diagnostic_causes.csv")

    inv_f = [r for r in inv if r["snapshot_date_key"] == FROZEN]
    diag_f = [r for r in diag if r["snapshot_date_key"] == FROZEN]
    bridge_f = [r for r in bridge if r["snapshot_date_key"] == FROZEN]

    eligible = {r["unit_key"] for r in inv_f
                if r["inventory_status"] == "AVAILABLE" and int(r["unsold_days_dom"]) > OVERDUE}
    diagnosed = {r["unit_key"] for r in diag_f}
    unexplained = eligible - diagnosed

    # attribution sums per diagnostic (frozen)
    asum = collections.defaultdict(Decimal)
    for r in bridge_f:
        asum[r["diagnostic_id"]] += Decimal(r["attribution_score"])
    bad = {k: v for k, v in asum.items() if abs(v - Decimal("1")) > Decimal("0.0000001")}

    causes = {r["primary_cause_code"] for r in diag_f}
    causes_all |= causes
    for r in diag_f:
        diag_ids_global[r["diagnostic_id"]] += 1

    # snapshot leak: any non-frozen rows remain? (should be 0 after freeze; report source volume)
    leak = sum(1 for r in diag if r["snapshot_date_key"] != FROZEN)

    tot_elig += len(eligible); tot_diag += len(diag_f); tot_unexpl += len(unexplained)
    attr_violations += [(pk, k, str(v)) for k, v in list(bad.items())[:3]]

    print(f"project_{pk}: inv@frozen={len(inv_f):>6} | eligible(AVAIL&DOM>{OVERDUE})={len(eligible):>5} "
          f"| diag@frozen={len(diag_f):>5} | UNEXPLAINED={len(unexplained):>4} "
          f"| attr!=1={len(bad)} | dropped_offsnapshot_diag={leak}")
    if unexplained:
        print(f"    !! sample unexplained unit_keys: {sorted(unexplained)[:8]}")

print("\n=== AGGREGATE (frozen 20260630) ===")
print(f"total eligible          : {tot_elig}")
print(f"total diagnostics        : {tot_diag}")
print(f"total UNEXPLAINED (gate3): {tot_unexpl}   -> {'PASS' if tot_unexpl==0 else 'FAIL'}")
dup = {k: c for k, c in diag_ids_global.items() if c > 1}
print(f"duplicate diagnostic_id  : {len(dup)}   -> {'PASS' if not dup else 'FAIL'}")
print(f"attribution!=1.000 count : {len(attr_violations)}   -> {'PASS' if not attr_violations else 'FAIL'}")
missing_core = CORE_8 - causes_all
extra = causes_all - CORE_8
print(f"8/8 core cause coverage  : {'PASS' if not missing_core else 'FAIL missing '+str(missing_core)}")
print(f"  core present   : {sorted(causes_all & CORE_8)}")
print(f"  extra (non-core): {sorted(extra)}")
