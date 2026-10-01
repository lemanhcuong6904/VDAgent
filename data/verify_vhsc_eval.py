"""Compare all generated eval SQL queries with their ground truth on PostgreSQL dev."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "mock" / "vhsc_20260630" / "eval_test_cases.json"


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    for case in cases:
        result = subprocess.run(
            ["docker", "exec", "vdagent-dw-dev", "psql", "-U", "postgres", "-d", "vdagent_dw_dev",
             "-v", "ON_ERROR_STOP=1", "-A", "-t", "-c", case["expected_sql_query"]],
            text=True, capture_output=True, check=True,
        )
        actual = [line for line in result.stdout.splitlines() if line]
        if actual != case["ground_truth_causes"]:
            raise AssertionError(f"{case['test_case_id']}: expected {case['ground_truth_causes']}, got {actual}")
    print(f"PASS: {len(cases)} eval SQL cases match ground truth on PostgreSQL dev")


if __name__ == "__main__":
    main()
