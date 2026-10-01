"""Step 1 of the real-DW demo: the Data agent's `fetch_units` over the DATA team's warehouse in Postgres.

Same Backend MCP tools as `test_steps.py`, with `RealEstateWarehouse` pointed at a `postgresql://` DSN. Skips without
`VDAGENT_TEST_PG_DSN` (see `backend/tests/warehouse/test_re_pg.py`). Snapshot and semantic version are the warehouse's own.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.scopes import REAL_SCOPES
from vdagent_backend.warehouse import RealEstateWarehouse, Warehouse
from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.mcp import McpTools
from vdagent_backend.scopes import UserScopes
from vdagent_backend.core import McpIdentity
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_data.steps import run_step
from vdagent_data.tests.conftest import ALICE, BOB, GRANTS, NOW, McpPort

DSN = os.environ.get("VDAGENT_TEST_PG_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="VDAGENT_TEST_PG_DSN not set (real warehouse in Postgres)")
SNAPSHOT, SEMANTIC = "SNAP-20260630-01", "3.1.0"
SUBJECT, SUBJECT_KEY = "OCP-U00001", "100001"  # project 100 (Alice); project 200 belongs to Bob


class RealTools:
    """The Backend `McpTools` over Postgres with the grants of `backend/config.yaml` (test adapter, as `GrantedTools`)."""

    def __init__(self, db: AsyncEngine, warehouse_db: str) -> None:
        self.tools = McpTools(ArtifactService(db), Warehouse(warehouse_db, 2.0),
                              re_warehouse=RealEstateWarehouse(DSN, 20.0), scopes=UserScopes(db))

    async def call(self, identity: McpIdentity, name: str, args: dict[str, Any]):  # noqa: ANN201
        return await self.tools.call(identity, GRANTS.get(identity.agent, frozenset()), name, args)


@pytest.fixture
async def tools(tmp_path: Path) -> AsyncIterator[RealTools]:
    path = str(tmp_path / "backend.db")
    await asyncio.to_thread(migrate, sqlite_url(path))
    engine = create_database(sqlite_url(path))
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", [(ALICE, "Alice", NOW), (BOB, "Bob", NOW)])
        for user in (ALICE, BOB):
            conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, created_at) VALUES (?, ?, 'data', 'running', ?)",
                         (f"t_{user}", user, NOW))
            conn.execute(
                "INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                " VALUES (?, ?, ?, 'data', 'orchestrator', 1, 'step', 'running', ?)", (f"inv_{user}", f"t_{user}", user, NOW))
        conn.executemany("INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, ?, ?)", REAL_SCOPES)
    conn.close()
    yield RealTools(engine, str(tmp_path / "warehouse.db"))
    await engine.dispose()


def port(tools: RealTools, user: str = ALICE) -> McpPort:
    return McpPort(tools, McpIdentity(user_id=user, agent="data", invocation_id=f"inv_{user}", task_id=f"t_{user}"))  # type: ignore[arg-type]


def step(user: str, scope: list[str], spec: dict[str, Any] | None = None, operation: str = "fetch_units") -> StepSpec:
    return StepSpec.model_validate({
        "run_id": f"t_{user}", "plan_id": "pl_real", "step_id": "B1", "idempotency_key": "pl_real:B1", "operation": operation,
        "spec": spec if spec is not None else {"subject_unit_code": SUBJECT},
        "user_context": {"user_id": user, "authorized_scope": {"project_ids": scope, "zone_ids": []}},
        "snapshot_id": SNAPSHOT, "semantic_config_version": SEMANTIC, "original_question": f"Vì sao căn {SUBJECT} bán chậm?",
    })


async def artifacts_of(p: McpPort, report: AgentReport) -> dict[str, dict[str, Any]]:
    return {r.artifact_type.value: await p.call("artifact_get", {"artifact_id": r.artifact_id, "version": r.version})
            for r in report.artifact_refs}


async def test_scopes_for_the_real_warehouse_are_the_real_projects() -> None:
    assert {(u, p) for u, p, _ in REAL_SCOPES} >= {(ALICE, "100"), (BOB, "200")}


async def test_fetch_units_completes_on_the_real_warehouse(tools: RealTools) -> None:
    p = port(tools)
    report = await run_step(step(ALICE, ["100"]), p)
    assert report.state == "completed", report.error
    assert report.snapshot_id == SNAPSHOT and report.semantic_config_version == SEMANTIC
    assert sorted(r.artifact_type.value for r in report.artifact_refs) == ["dataset", "dq", "metric"]


async def test_the_dataset_holds_the_real_unit_and_its_real_rows(tools: RealTools) -> None:
    p = port(tools)
    report = await run_step(step(ALICE, ["100"]), p)
    payload = (await artifacts_of(p, report))["dataset"]["payload"]
    assert payload["snapshot"]["snapshot_id"] == SNAPSHOT and payload["snapshot"]["snapshot_date_key"] == 20260630
    [unit] = payload["tables"]["dim_unit_master"]
    assert (unit["unit_key"], unit["unit_code"], unit["project_key"]) == (SUBJECT_KEY, SUBJECT, "100")
    assert payload["tables"]["fact_unit_inventory_snapshot"][0]["unit_key"] == SUBJECT_KEY
    assert payload["semantic_config"]["overdue_threshold_days"]["status"] == "APPROVED"
    assert payload["semantic_config"]["peer_area_tolerance_pct"]["ratio"] == "0.10"


async def test_metrics_come_from_the_real_rows_and_nothing_is_invented(tools: RealTools) -> None:
    p = port(tools)
    report = await run_step(step(ALICE, ["100"]), p)
    arts = await artifacts_of(p, report)
    rows = {m["metric_id"]: m for m in arts["metric"]["payload"]["metrics"]}
    inventory = arts["dataset"]["payload"]["tables"]["fact_unit_inventory_snapshot"][0]
    assert rows["dom_days"]["value"] == inventory["unsold_days_dom"]
    assert rows["net_price_per_m2_vnd"]["value"] == inventory["net_price_per_m2"]
    assert rows["net_area_m2"]["value"] == arts["dataset"]["payload"]["tables"]["dim_unit_master"][0]["net_area_m2"]
    assert all(m["value"] is not None or any(w.startswith(("METRIC_UNAVAILABLE", "WINDOW_INCOMPLETE")) for w in report.warnings)
               for m in rows.values())


async def test_the_peer_candidates_are_real_units_of_the_same_type_inside_the_scope(tools: RealTools) -> None:
    p = port(tools)
    report = await run_step(step(ALICE, ["100"], {"subject_unit_code": SUBJECT, "population": "peer_candidates"}), p)
    assert report.state == "completed", report.error
    units = (await artifacts_of(p, report))["dataset"]["payload"]["tables"]["dim_unit_master"]
    # the scope comes from the Backend (Alice: projects 100 and 400), not from the step's own user_context (["100"])
    assert len(units) > 1 and {u["project_key"] for u in units} <= {"100", "400"} and len({u["unit_type"] for u in units}) == 1
    assert not {u["project_key"] for u in units} & {"200", "300", "500"}


async def test_a_user_cannot_read_another_users_project(tools: RealTools) -> None:
    report = await run_step(step(BOB, ["200"]), port(tools, BOB))
    assert report.state == "failed" and report.error and report.error.code == "UNIT_NOT_FOUND"
    assert not report.artifact_refs


async def test_a_snapshot_the_warehouse_does_not_have_is_refused(tools: RealTools) -> None:
    bad = step(ALICE, ["100"]).model_copy(update={"snapshot_id": "SNAP-2026-09-28"})
    report = await run_step(bad, port(tools))
    assert report.state == "rejected" and report.error and report.error.code == "SNAPSHOT_UNKNOWN"
