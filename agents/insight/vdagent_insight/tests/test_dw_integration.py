"""WS3: Insight consumes the canonical Data artifacts (re_dataset@1 / re_metric@1 / re_dq@1) of the real-estate DW.

The Data step runs first against a freshly built `re_warehouse` and the Backend's real MCP tools (fixtures shared with
the Data tests); Insight then reads those artifacts through `artifact_get`. No export pack, no LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_data.steps import run_step as run_data_step
from vdagent_data.tests.conftest import ALICE, McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_data.tests.test_steps import step as data_step
from vdagent_insight import export_reader
from vdagent_insight.settings import CONFIG_DIR, SemanticConfigRegistry, load_llm_config
from vdagent_insight.stepspec import StepEnv, run_step
from vdagent_insight.store import InsightStore

HERO = "U-PRJ-X-A12-08"


@pytest.fixture
def env(tmp_path: Path) -> StepEnv:
    return StepEnv(registry=SemanticConfigRegistry(CONFIG_DIR), llm=load_llm_config(CONFIG_DIR / "llm.yaml"),
                   store=InsightStore(tmp_path / "insight.db"))


@pytest.fixture
def no_export_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """The integrated path must never read the Insight export pack or fixtures."""

    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("export pack read on the integrated path")

    monkeypatch.setattr(export_reader, "_load", refuse)


async def data_refs(port: McpPort, **over: Any) -> list[dict[str, Any]]:
    report = await run_data_step(data_step(**over), port)
    assert report.state == "completed"
    return [r.model_dump(mode="json") for r in report.artifact_refs]


def insight_step(refs: list[dict[str, Any]], **over: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": f"t_{ALICE}", "plan_id": "pl_ws3", "step_id": "B2", "idempotency_key": "pl_ws3:B2",
        "operation": "explain_unit",
        "spec": {"intent": "SLOW_MOVING_INVESTIGATION", "tasks": ["T1", "T7"],
                 "analysis_scope": {"level": "UNIT", "project_ids": ["PRJ-X"], "unit_ids": [HERO]}},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X"], "zone_ids": []}},
        "snapshot_id": "SNAP-2026-09-28", "semantic_config_version": "sc-1",
        "input_refs": refs, "original_question": "Vì sao căn A12-08 bán chậm?",
    }
    fields.update(over)
    return StepSpec.model_validate(fields)


async def the_insight(port: McpPort, report: AgentReport) -> dict[str, Any]:
    assert report.state == "completed", report
    [ref] = report.artifact_refs
    assert ref.artifact_type.value == "insight"
    return await port.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})


def _values(insight: dict[str, Any]) -> list[str]:
    return [b["value"] for i in insight["payload"]["insight"]["insights"] for b in i["claim"]["numeric_bindings"]]


async def test_golden_insight_from_the_canonical_dataset(alice: McpPort, env: StepEnv, no_export_pack: None) -> None:
    refs = await data_refs(alice)
    report = await run_step(insight_step(refs), alice.as_agent("insight"), env)
    art = await the_insight(alice, report)

    assert art["schema_version"] == "insight.v2" and art["producer"]["agent"] == "insight"
    assert art["snapshot_refs"] == ["SNAP-2026-09-28"] and art["semantic_config_version"] == "sc-1"
    assert art["input_artifact_refs"] == refs  # the exact Data dataset/metric/dq, pinned by hash
    assert {r["artifact_id"] for r in art["evidence_refs"]} <= {r["artifact_id"] for r in refs}
    assert art["evidence_refs"], "a KEY/ROOT_CAUSE insight cites Data evidence"

    insights = art["payload"]["insight"]["insights"]
    root = [i for i in insights if i["cause_code"] == "OVERPRICED_VS_PEER"]
    assert root and root[0]["subject"]["id"] == HERO
    assert "138" in _values(art)  # DOM from the DW mart
    assert "12.40" not in _values(art)  # the mart's peer spread: Compare owns peer facts (insight_evidence@2)
    from vdagent_contracts.insight_evidence import parse_evidence  # noqa: PLC0415
    assert any(i.requires == "comparison" for f in parse_evidence(art["payload"]).findings for i in f.visual_intents)
    assert art["payload"]["insight"]["summary"]["narrative_mode"] == "TEMPLATE"


async def test_data_limitations_are_carried_not_filled(alice: McpPort, env: StepEnv) -> None:
    report = await run_step(insight_step(await data_refs(alice)), alice.as_agent("insight"), env)
    art = await the_insight(alice, report)
    for code in ("WINDOW_INCOMPLETE:inquiry_leads_30d:3", "METRIC_UNAVAILABLE:discount_pct",
                 "METRIC_UNAVAILABLE:subsidy_duration_mo", "BLOCKED:D2b_segment_mapping"):
        assert code in art["limitations"]
    assert report.partial is True


async def test_raw_dw_values_are_kept(alice: McpPort, env: StepEnv) -> None:
    report = await run_step(insight_step(await data_refs(alice)), alice.as_agent("insight"), env)
    art = await the_insight(alice, report)
    view = art["payload"]["input_view"]
    [project] = view["dim_project_profile"]
    assert project["segment"] == "HIGH_END"  # D2b unresolved: raw value, no enum mapping
    [unit] = [u for u in view["dim_unit_master"] if u["unit_key"] == HERO]
    assert unit["unit_key"] == HERO and unit["project_key"] == "PRJ-X"  # canonical TEXT keys
    [inv] = [r for r in view["fact_unit_inventory_snapshot"] if r["unit_key"] == HERO]
    assert inv["subsidy_duration_mo"] is None and inv["channel_key"] == "CH-01"
    assert not [u for u in view["dim_unit_master"] if u["project_key"] != "PRJ-X"]


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"snapshot_id": "SNAP-2026-08-31"}, "SNAPSHOT_MISMATCH"),
        ({"semantic_config_version": "3.1.0"}, "SEMANTIC_VERSION_MISMATCH"),
        ({"operation": "draw_chart"}, "UNKNOWN_OPERATION"),
        ({"spec": {"intent": "SLOW_MOVING_INVESTIGATION"}}, "INVALID_SPEC"),
    ],
)
async def test_mismatches_are_rejected(alice: McpPort, env: StepEnv, over: dict[str, Any], code: str) -> None:
    report = await run_step(insight_step(await data_refs(alice), **over), alice.as_agent("insight"), env)
    assert report.state == "rejected" and report.error is not None and report.error.code == code
    kinds = {a["artifact_type"] for a in (await alice.call("artifact_list", {}))["artifacts"]}
    assert "insight" not in kinds


async def test_invalid_ref_is_rejected(alice: McpPort, env: StepEnv) -> None:
    refs = await data_refs(alice)
    refs[0] = {**refs[0], "content_hash": "0" * 64}
    report = await run_step(insight_step(refs), alice.as_agent("insight"), env)
    assert report.error is not None and report.error.code == "INPUT_HASH_MISMATCH"


async def test_scope_outside_the_dataset_is_rejected(alice: McpPort, env: StepEnv) -> None:
    refs = await data_refs(alice)
    spec = {"intent": "SLOW_MOVING_INVESTIGATION", "tasks": ["T1"],
            "analysis_scope": {"level": "UNIT", "project_ids": ["PRJ-Y"], "unit_ids": ["U-PRJ-Y-D12-09"]}}
    report = await run_step(insight_step(refs, spec=spec), alice.as_agent("insight"), env)
    assert report.state in ("rejected", "failed") and report.error is not None
    assert report.error.code in ("SCOPE_VIOLATION", "E04")
