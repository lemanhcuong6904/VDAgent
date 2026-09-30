from __future__ import annotations

import json
from pathlib import Path

from .contracts import ChartPolicy
from .errors import ChartError

POLICY_DIR = Path(__file__).parent / "demo"


def load_policy(ruleset_version: str) -> ChartPolicy:
    if ruleset_version != "chart-policy/demo-1.0":
        raise ChartError(
            "POL-001", f"unknown chart policy {ruleset_version!r}", "policy"
        )
    raw = json.loads(
        (POLICY_DIR / "chart-policy-demo-1.0.json").read_text(encoding="utf-8")
    )
    return ChartPolicy(
        ruleset_version=raw["ruleset_version"],
        allowed_chart_types=tuple(raw["allowed_chart_types"]),
        max_categories=raw["limits"]["max_categories"],
        max_series=raw["limits"]["max_series"],
        max_points=raw["limits"]["max_points"],
        allow_dual_axis=raw["global"]["allow_dual_axis"],
        allow_imputation=raw["global"]["allow_imputation"],
        allow_silent_truncation=raw["global"]["allow_silent_truncation"],
        fallback_chart_type=raw["fallback_chart_type"],
    )
