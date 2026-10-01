"""The five canonical packs must fit into the same 16-table warehouse."""

import csv
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


WAREHOUSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WAREHOUSE))
PROJECT_KEYS = (100, 200, 300, 400, 500)
GLOBAL_PRIMARY_KEYS = {
    "fact_sales_funnel_daily": "funnel_event_id",
    "dim_secondary_market_comps": "comp_id",
    "fact_unit_price_history": "price_event_id",
}


@contextmanager
def scratch_dir():
    folder = WAREHOUSE / "tests" / f"scratch_{uuid.uuid4().hex}"
    folder.mkdir()
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


class GlobalPrimaryKeyTest(unittest.TestCase):
    def test_rekey_preserves_source_id_and_is_repeatable(self):
        from organize_pack import rekey_comp_ids, rekey_numeric_event

        with scratch_dir() as temp_dir:
            numeric_path = temp_dir / "events.csv"
            numeric_path.write_text("funnel_event_id\n1\n2\n", encoding="utf-8")
            rekey_numeric_event(numeric_path, "funnel_event_id", 100)
            rekey_numeric_event(numeric_path, "funnel_event_id", 100)
            with numeric_path.open(encoding="utf-8", newline="") as handle:
                values = [int(row["funnel_event_id"]) for row in csv.DictReader(handle)]
            self.assertEqual([10_000_000_001, 10_000_000_002], values)

            comp_path = temp_dir / "comps.csv"
            comp_path.write_text("comp_id\nCOMP-00001\n", encoding="utf-8")
            rekey_comp_ids(comp_path, "OCP-")
            rekey_comp_ids(comp_path, "OCP-")
            with comp_path.open(encoding="utf-8", newline="") as handle:
                values = [row["comp_id"] for row in csv.DictReader(handle)]
            self.assertEqual(["OCP-COMP-00001"], values)

    def test_quality_gate_rejects_cross_project_collision(self):
        from verify_warehouse import validate_global_keys

        with scratch_dir() as temp_dir:
            for project_key in (100, 200):
                folder = temp_dir / f"project_{project_key}"
                folder.mkdir()
                with (folder / "fact_sales_funnel_daily.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["funnel_event_id"])
                    writer.writerow([1])

            errors = validate_global_keys(
                temp_dir, (100, 200),
                {"fact_sales_funnel_daily": [("funnel_event_id",)]},
            )
        self.assertTrue(any("funnel_event_id" in error for error in errors))

    def test_canonical_packs_can_share_primary_keys(self):
        for table, column in GLOBAL_PRIMARY_KEYS.items():
            with self.subTest(table=table):
                owners = {}
                collisions = []
                for project_key in PROJECT_KEYS:
                    path = WAREHOUSE / f"project_{project_key}" / f"{table}.csv"
                    with path.open(encoding="utf-8-sig", newline="") as handle:
                        for row in csv.DictReader(handle):
                            value = row[column]
                            if value in owners:
                                collisions.append((value, owners[value], project_key))
                            else:
                                owners[value] = project_key
                self.assertEqual(
                    [], collisions[:3],
                    f"{table}.{column}: {len(collisions)} duplicate rows",
                )


if __name__ == "__main__":
    unittest.main()
