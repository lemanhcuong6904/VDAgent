"""The existing backend must be able to query a read-only Smart City projection."""

import unittest
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from data.build_vhsc_sqlite import build_projection  # noqa: E402
from vdagent_backend.mcp import sql  # noqa: E402


class SmartCitySQLiteProjection(unittest.TestCase):
    def test_backend_read_only_tools_see_sixteen_tables_and_3000_units(self):
        (ROOT / "var").mkdir(exist_ok=True)
        db = ROOT / "var" / f"vhsc_test_{os.getpid()}.db"
        try:
            build_projection(ROOT / "data" / "mock" / "vhsc_20260630", db)
            tables = sql.warehouse_tables(str(db), timeout_s=10)
            self.assertEqual(len(tables), 16)
            self.assertEqual(next(t["row_count"] for t in tables if t["name"] == "dim_unit_master"), 3000)
            description = sql.warehouse_describe(str(db), "dim_unit_master", timeout_s=10)
            self.assertIn("unit_code", {c["name"] for c in description["columns"]})
            result = sql.warehouse_query(
                str(db),
                "SELECT COUNT(*) AS n FROM fact_unit_inventory_snapshot "
                "WHERE project_key = 200 AND snapshot_date_key = 20260630",
                timeout_s=10,
            )
            self.assertEqual(result.rows, [[3000]])
            result = sql.warehouse_query(
                str(db),
                "SELECT COUNT(*) AS n FROM dm_unit_friction_diagnostics "
                "WHERE primary_cause_code = 'LEGAL_PERMIT_BARRIER'",
                timeout_s=10,
            )
            self.assertEqual(result.rows, [[16]])
        finally:
            db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
