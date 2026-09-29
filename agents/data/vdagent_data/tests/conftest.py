from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.re_warehouse import build  # test-only (DEC-032)
from vdagent_contracts.messages import StepSpec


@pytest.fixture(scope="session")
def dw_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(Path(tmp_path_factory.mktemp("dw")) / "re.db")
    build(path)
    return path


def step(operation: str = "aggregate_metrics", spec: dict[str, Any] | None = None, **overrides: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": "t_1",
        "plan_id": "PLAN-1",
        "step_id": "B1",
        "idempotency_key": "PLAN-1:B1",
        "operation": operation,
        "spec": spec if spec is not None else {
            "objective": "DOM trung bình theo nhóm tầng",
            "scope": {"mentions": [{"text": "Tòa Landmark 1", "kind_hint": "ZONE"}], "scope_all": False},
            "metrics": ["avg_dom_unsold"],
            "group_by": ["floor_band"],
        },
        "user_context": {"user_id": "u_000000000001", "authorized_scope": {"project_ids": ["PRJ-X"]}},
        "deadline_s": 90,
        "original_question": "DOM trung bình theo nhóm tầng của Tòa Landmark 1?",
    }
    if "step_id" in overrides and "idempotency_key" not in overrides:
        overrides["idempotency_key"] = f"PLAN-1:{overrides['step_id']}"
    fields.update(overrides)
    return StepSpec.model_validate(fields)
