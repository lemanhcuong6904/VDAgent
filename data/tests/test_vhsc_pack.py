"""Contract checks for the synthetic Smart City project pack."""

import csv
import json
import unittest
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data" / "mock" / "vhsc_20260630"
REGISTRY = ROOT / "warehouse" / "id_registry.json"
TABLES = {
    "snapshot_manifest", "semantic_config", "dim_date", "dim_infrastructure_assets",
    "dim_project_profile", "dim_zone_master", "dim_unit_master", "dim_sales_channel",
    "dim_secondary_market_comps", "fact_market_macro_monthly", "fact_unit_price_history",
    "fact_sales_funnel_daily", "fact_unit_inventory_snapshot",
    "fact_sales_channel_performance", "dm_unit_friction_diagnostics", "unit_diagnostic_causes",
}


def rows(table):
    with (PACK / f"{table}.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class SmartCityPackContract(unittest.TestCase):
    def test_registry_identity_and_foreign_keys(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        project = next(p for p in registry["projects"] if p["project_key"] == 200)
        self.assertEqual(project["project_id"], "PRJ-VHSC")
        self.assertEqual({p.name[:-4] for p in PACK.glob("*.csv")}, TABLES)

        projects = rows("dim_project_profile")
        self.assertEqual([(p["project_key"], p["project_id"]) for p in projects], [("200", "PRJ-VHSC")])
        units = rows("dim_unit_master")
        self.assertEqual(len(units), 3000)
        keys = {int(u["unit_key"]) for u in units}
        self.assertEqual(keys, set(range(200001, 203001)))
        self.assertEqual({u["unit_code"] for u in units}, {f"SMC-U{i:05d}" for i in range(1, 3001)})
        self.assertEqual(len({u["unit_id"] for u in units}), 3000)
        self.assertEqual({u["project_key"] for u in units}, {"200"})

        zones = {z["zone_key"] for z in rows("dim_zone_master")}
        channels = {c["channel_key"] for c in rows("dim_sales_channel")}
        infra = {a["infra_key"] for a in rows("dim_infrastructure_assets")}
        self.assertTrue(all(201 <= int(k) <= 299 for k in zones))
        self.assertTrue(all(2001 <= int(k) <= 2099 for k in channels))
        self.assertTrue(all(2101 <= int(k) <= 2199 for k in infra))
        self.assertTrue(all(z["project_key"] == "200" for z in rows("dim_zone_master")))
        self.assertTrue(all(u["zone_key"] in zones for u in units))
        self.assertTrue(all(p["primary_infra_id"] in {a["infra_id"] for a in rows("dim_infrastructure_assets")} for p in projects))

        inventory = rows("fact_unit_inventory_snapshot")
        self.assertEqual(len(inventory), 3000)
        self.assertEqual({int(i["unit_key"]) for i in inventory}, keys)
        self.assertEqual(len({(i["unit_key"], i["snapshot_date_key"]) for i in inventory}), 3000)
        self.assertTrue(all(i["project_key"] == "200" and i["zone_key"] in zones and i["channel_key"] in channels for i in inventory))
        self.assertTrue(all(int(f["unit_key"]) in keys for f in rows("fact_sales_funnel_daily")))
        self.assertTrue(all(int(h["unit_key"]) in keys for h in rows("fact_unit_price_history")))

    def test_snapshot_and_diagnostics(self):
        manifest = rows("snapshot_manifest")
        self.assertEqual(len(manifest), 1)
        self.assertEqual((manifest[0]["snapshot_id"], manifest[0]["snapshot_date"]),
                         ("SNAP-20260630-01", "2026-06-30"))
        inventory = rows("fact_unit_inventory_snapshot")
        eligible = set()
        for item in inventory:
            self.assertEqual(item["snapshot_date_key"], "20260630")
            status = item["inventory_status"]
            release = date.fromisoformat(item["release_date"])
            sold = date.fromisoformat(item["sold_date"]) if item["sold_date"] else None
            self.assertGreaterEqual(Decimal(item["asking_price_vnd"]), Decimal(item["net_price_vnd"]))
            self.assertTrue(sold is None if status == "AVAILABLE" else True)
            if status == "SOLD":
                self.assertIsNotNone(sold)
                self.assertGreaterEqual(sold, release)
            dom = ((sold or date(2026, 6, 30)) - release).days
            self.assertEqual(int(item["unsold_days_dom"]), dom)
            overdue = status == "AVAILABLE" and dom > 90
            self.assertEqual(item["is_overdue_flag"], "t" if overdue else "f")
            if overdue:
                eligible.add(item["unit_key"])

        diagnostics = rows("dm_unit_friction_diagnostics")
        self.assertEqual({d["unit_key"] for d in diagnostics}, eligible)
        self.assertEqual(len({d["diagnostic_id"] for d in diagnostics}), len(diagnostics))
        causes = rows("unit_diagnostic_causes")
        by_diag = defaultdict(list)
        for cause in causes:
            by_diag[cause["diagnostic_id"]].append(cause)
        self.assertEqual(set(by_diag), {d["diagnostic_id"] for d in diagnostics})
        for diag in diagnostics:
            group = by_diag[diag["diagnostic_id"]]
            self.assertEqual(sum((Decimal(c["attribution_score"]) for c in group), Decimal(0)), Decimal("1.000"))
            self.assertEqual([c["cause_code"] for c in group if c["severity_rank"] == "1"],
                             [diag["primary_cause_code"]])
        self.assertEqual(len({d["primary_cause_code"] for d in diagnostics}), 8)
        self.assertGreaterEqual(min(Counter(d["primary_cause_code"] for d in diagnostics).values()), 16)

    def test_provisional_tc_fixtures_are_explicit(self):
        cases = json.loads((PACK / "tc_assumptions.json").read_text(encoding="utf-8"))
        self.assertEqual(set(cases), {"TC-13", "TC-15"})
        self.assertTrue(all(case["status"] == "PROVISIONAL_PENDING_BA" for case in cases.values()))
        scenarios = {s["unit_id"]: s for s in json.loads((PACK / "expected_scenarios.json").read_text(encoding="utf-8"))}
        for case in cases.values():
            self.assertIn(case["unit_id"], scenarios)
            self.assertEqual(scenarios[case["unit_id"]]["expected_primary_cause"], case["expected_primary_cause"])

        units = {u["unit_id"]: u for u in rows("dim_unit_master")}
        legal = units[cases["TC-13"]["unit_id"]]
        attrs = json.loads(legal["ext_attributes"])
        self.assertTrue(attrs["fictional_phase_fixture"])
        self.assertFalse(attrs["phase_sales_permit_issued"])
        funnel = [f for f in rows("fact_sales_funnel_daily")
                  if f["unit_key"] == units[cases["TC-15"]["unit_id"]]["unit_key"]]
        self.assertGreaterEqual(sum(int(f["web_listing_views"]) for f in funnel), 300)
        self.assertGreaterEqual(sum(int(f["booking_reservations"]) for f in funnel), 10)
        self.assertGreaterEqual(sum(int(f["booking_cancellations"]) for f in funnel), 8)

    def test_pack_manifest_for_assembler(self):
        manifest = json.loads((PACK / "pack_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["project_key"], manifest["project_id"]), (200, "PRJ-VHSC"))
        self.assertEqual(manifest["snapshot_id"], "SNAP-20260630-01")
        self.assertEqual(manifest["registry_version"], "3.1.1")
        self.assertEqual(set(manifest["table_order"]), TABLES)
        self.assertEqual(manifest["row_counts"], {table: len(rows(table)) for table in TABLES})


if __name__ == "__main__":
    unittest.main()
