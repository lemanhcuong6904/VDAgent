"""Insight → Chart on the DATA team's warehouse in Postgres (real keys are numeric-looking TEXT, the mock's are not).

Data → Insight (TEMPLATE) + Compare → Chart for OCP-U01325 over the Backend MCP tools pointed at a `postgresql://` DSN.
Skips without `VDAGENT_TEST_PG_DSN` (see backend/tests/warehouse/test_re_pg.py).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.persistence import create_database, migrate, sqlite_url
from vdagent_backend.scopes import REAL_SCOPES
from vdagent_chart.stepspec import run_step as run_chart
from vdagent_chart.tests.test_ws4_integration import assert_bindings_resolve, by_question, chart_step, charts
from vdagent_compare.stepspec import run_step as run_compare
from vdagent_compare.tests.test_dw_integration import compare_step
from vdagent_contracts.insight_evidence import parse_evidence
from vdagent_data.steps import run_step as run_data
from vdagent_data.tests.conftest import ALICE, BOB, NOW, McpPort
from vdagent_data.tests.test_real_dw import DSN, SEMANTIC, SNAPSHOT, RealTools, port
from vdagent_data.tests.test_steps import step as data_step
from vdagent_insight.settings import CONFIG_DIR, SemanticConfigRegistry, load_llm_config
from vdagent_insight.stepspec import StepEnv
from vdagent_insight.stepspec import run_step as run_insight
from vdagent_insight.store import InsightStore
from vdagent_insight.tests.test_dw_integration import insight_step

pytestmark = pytest.mark.skipif(not DSN, reason="VDAGENT_TEST_PG_DSN not set (real warehouse in Postgres)")
UNIT, SCOPE = "OCP-U01325", {"user_id": ALICE, "authorized_scope": {"project_ids": ["100"], "zone_ids": []}}
PINS = {"snapshot_id": SNAPSHOT, "semantic_config_version": SEMANTIC, "user_context": SCOPE,
        "original_question": f"Vì sao căn {UNIT} bán chậm?"}


@pytest.fixture
async def tools(tmp_path: Path) -> AsyncIterator[RealTools]:
    path = str(tmp_path / "backend.db")
    await asyncio.to_thread(migrate, sqlite_url(path))
    engine = create_database(sqlite_url(path))
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)", [(ALICE, "Alice", NOW), (BOB, "Bob", NOW)])
        conn.execute("INSERT INTO tasks (id, user_id, root_agent, status, created_at) VALUES (?, ?, 'data', 'running', ?)",
                     (f"t_{ALICE}", ALICE, NOW))
        for agent, inv in (("data", f"inv_{ALICE}"), *((a, f"inv_{ALICE}_{a}") for a in ("insight", "compare", "chart"))):
            conn.execute("INSERT INTO invocations (id, task_id, user_id, agent, caller, depth, inbound_text, status, created_at)"
                         " VALUES (?, ?, ?, ?, 'orchestrator', 1, 'step', 'running', ?)", (inv, f"t_{ALICE}", ALICE, agent, NOW))
        conn.executemany("INSERT INTO user_scopes (user_id, project_id, zone_id) VALUES (?, ?, ?)", REAL_SCOPES)
    conn.close()
    yield RealTools(engine, str(tmp_path / "warehouse.db"))
    await engine.dispose()


async def test_insight_kpis_and_peer_basis_on_the_real_warehouse(tools: RealTools, tmp_path: Path) -> None:
    alice: McpPort = port(tools)
    data = await run_data(data_step(spec={"subject_unit_code": UNIT, "population": "peer_candidates"}, **PINS), alice)
    assert data.state == "completed", data.error
    refs = [r.model_dump(mode="json") for r in data.artifact_refs]
    env = StepEnv(registry=SemanticConfigRegistry(CONFIG_DIR), llm=load_llm_config(CONFIG_DIR / "llm.yaml"),
                  store=InsightStore(tmp_path / "insight.db"))
    scope = {"intent": "SLOW_MOVING_INVESTIGATION", "tasks": ["T1", "T7"],
             "analysis_scope": {"level": "UNIT", "project_ids": ["100"], "unit_ids": ["101325"]}}
    ins = await run_insight(insight_step(refs, spec=scope, **PINS), alice.as_agent("insight"), env)
    cmp = await run_compare(compare_step(refs, spec={"subject": {"entityType": "unit", "entityCode": UNIT},
                                                     "comparisonMode": "peer_group"}, **PINS), alice.as_agent("compare"))
    assert ins.state == cmp.state == "completed", (ins.error, cmp.error)

    insight = await alice.call("artifact_get", {"artifact_id": ins.artifact_refs[0].artifact_id})
    evidence = parse_evidence(insight["payload"])
    assert not [m for f in evidence.findings for m in f.metrics if m.metric_id.endswith(("price_spread_vs_peer_pct", "peer_n"))]
    assert not [m for f in evidence.findings for m in f.metrics if m.not_chartable_reason == "SOURCE_UNRESOLVED"]

    upstream = [r.model_dump(mode="json") for r in [*ins.artifact_refs, *cmp.artifact_refs]]
    report = await run_chart(chart_step(upstream, **PINS), alice.as_agent("chart"))
    specs = await charts(alice, report)
    kpis = {b["metric_id"]: b["value_exact"] for s in by_question(specs, "current_value") for b in s["payload"]["bindings"]}
    assert kpis == {"fact_unit_inventory_snapshot.unsold_days_dom": "364",
                    "dm_unit_friction_diagnostics.physical_defect_penalty": "95",
                    "dm_unit_friction_diagnostics.secondary_price_gap_pct": "12.54",
                    "dm_unit_friction_diagnostics.funnel_dropoff_rate_pct": "70.00"}
    assert not any(w.startswith("PEER_BASIS_DIFFERS") for w in report.warnings)  # one peer truth: Compare's
    for spec in specs:
        await assert_bindings_resolve(alice, spec)
