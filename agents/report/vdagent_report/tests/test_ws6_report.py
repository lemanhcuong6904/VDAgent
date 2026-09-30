"""WS6: Report consumes the real Insight / Comparison / Chart artifacts and writes an evidence-checked report.

Upstream runs for real (Data → Insight + Compare → Chart) on the Backend's MCP tools. No LLM, no Jev judge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vdagent_backend.db import artifacts as backend_artifacts
from vdagent_backend.mcp.tools import McpTools
from vdagent_chart.stepspec import resolve_pointer
from vdagent_chart.stepspec import run_step as run_chart
from vdagent_chart.tests.test_ws4_integration import chart_step, upstream
from vdagent_contracts.messages import StepSpec
from vdagent_data.tests.conftest import ALICE, BOB, McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_report.compose import SECTION_TITLES, Statement, validate_statements
from vdagent_report.stepspec import run_step

REPO = Path(__file__).resolve().parents[4]


async def full_upstream(port: McpPort, tmp_path: Path) -> dict[str, Any]:
    up = await upstream(port, tmp_path)
    chart = await run_chart(chart_step([up["insight"], up["comparison"], up["peer_definition"]]), port.as_agent("chart"))
    assert chart.state == "completed"
    up["chart_specs"] = [r.model_dump(mode="json") for r in chart.artifact_refs]
    return up


def report_step(refs: list[dict[str, Any]], **over: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": f"t_{ALICE}", "plan_id": "pl_ws6", "step_id": "B5", "idempotency_key": "pl_ws6:B5",
        "operation": "draft_report", "spec": {},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X"], "zone_ids": []}},
        "snapshot_id": "SNAP-2026-09-28", "semantic_config_version": "sc-1", "input_refs": refs,
        "original_question": "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo.",
    }
    fields.update(over)
    return StepSpec.model_validate(fields)


def all_refs(up: dict[str, Any]) -> list[dict[str, Any]]:
    return [up["insight"], up["peer_definition"], up["comparison"], *up["chart_specs"]]


async def the_report(port: McpPort, report: Any) -> dict[str, Any]:
    assert report.state == "completed", report
    [ref] = report.artifact_refs
    assert ref.artifact_type.value == "report"
    return await port.call("artifact_get", {"artifact_id": ref.artifact_id, "version": ref.version})


async def resolve(port: McpPort, source_ref: str) -> Any:
    ref, pointer = source_ref.split("#", 1)
    artifact_id, version = ref.split("@")
    art = await port.call("artifact_get", {"artifact_id": artifact_id, "version": int(version)})
    return resolve_pointer(art["payload"], pointer)


# ---- golden ---------------------------------------------------------------------------------------------------------


async def test_golden_report_from_real_artifacts(alice: McpPort, mcp_tools: McpTools, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    report = await run_step(report_step(all_refs(up)), alice.as_agent("report"))
    art = await the_report(alice, report)

    assert art["schema_version"] == "report@1" and art["producer"]["agent"] == "report"
    assert art["snapshot_refs"] == ["SNAP-2026-09-28"] and art["semantic_config_version"] == "sc-1"
    assert art["input_artifact_refs"][0] == up["dataset"] and up["comparison"] in art["input_artifact_refs"]
    payload = art["payload"]
    assert [s["title"] for s in payload["sections"]] == list(SECTION_TITLES)
    md = payload["markdown"]
    for value in ("138", "61", "72.500.000", "64.500.000", "12,40"):
        assert value in md, value
    assert len(payload["charts"]) + len(payload["tables"]) >= 2 and len(payload["charts"]) >= 2
    for chart in payload["charts"]:
        assert f"{{{{chart_spec:{chart['artifact_id']}@{chart['version']}}}}}" in md
    # every numeric statement resolves to the exact upstream value
    assert payload["statements"]
    for st in payload["statements"]:
        assert str(await resolve(alice, st["source_ref"])) == st["value_exact"], st
    assert payload["validation"]["result"] == "pass" and payload["validation"]["statements_checked"] == len(payload["statements"])
    assert payload["validation"]["chart_bindings_checked"] > 0
    # limitations and open blockers are stated, not hidden
    for code in ("METRIC_UNAVAILABLE:discount_pct", "WINDOW_INCOMPLETE:inquiry_leads_30d:3", "BLOCKED:B-2_min_peer_count"):
        assert code in art["limitations"]
    limits_text = payload["sections"][5]["markdown"]
    for blocker in ("B-11", "B-2", "D2b", "B-3", "B-12"):
        assert blocker in limits_text, blocker
    assert "gây ra" not in md.lower() and "nguyên nhân duy nhất" not in md.lower()  # no causal overclaim
    assert art["status"] == "PARTIAL"
    # delivered through the existing report path, chart_spec embeds validated by save_report
    delivered = await backend_artifacts.get_report(mcp_tools._db, ALICE, payload["delivery"]["report_id"])  # pyright: ignore[reportPrivateUsage]
    assert delivered is not None and delivered["markdown"] == md


async def test_actions_are_evidence_based_or_explained(alice: McpPort, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    art = await the_report(alice, await run_step(report_step(all_refs(up)), alice.as_agent("report")))
    actions = art["payload"]["actions"]
    assert all(a["source_ref"].startswith(up["insight"]["artifact_id"]) for a in actions["items"])
    if len(actions["items"]) < 2:
        assert actions["insufficient_evidence_note"]


# ---- modes and missing inputs ------------------------------------------------------------------------------------------


async def test_without_charts_the_report_uses_tables_and_says_so(alice: McpPort, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    report = await run_step(report_step([up["insight"], up["peer_definition"], up["comparison"]]), alice.as_agent("report"))
    art = await the_report(alice, report)
    assert art["payload"]["charts"] == [] and len(art["payload"]["tables"]) >= 2
    assert "UPSTREAM_MISSING:chart_spec" in art["limitations"]


@pytest.mark.parametrize("missing", ["insight", "comparison"])
async def test_one_analysis_missing(alice: McpPort, tmp_path: Path, missing: str) -> None:
    up = await full_upstream(alice, tmp_path)
    refs = [up["insight"]] if missing == "comparison" else [up["peer_definition"], up["comparison"]]
    report = await run_step(report_step(refs), alice.as_agent("report"))
    art = await the_report(alice, report)
    assert f"UPSTREAM_MISSING:{missing}" in art["limitations"] and art["status"] == "PARTIAL"
    assert [s["title"] for s in art["payload"]["sections"]] == list(SECTION_TITLES)


async def _refused(port: McpPort, step: StepSpec, code: str) -> None:
    report = await run_step(step, port.as_agent("report"))
    assert report.state in ("rejected", "failed") and report.error is not None, report
    assert report.error.code == code, report.error
    assert "report" not in {a["artifact_type"] for a in (await port.call("artifact_list", {}))["artifacts"]}


async def test_rejections(alice: McpPort, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    await _refused(alice, report_step([up["dataset"]]), "MISSING_INPUT")
    await _refused(alice, report_step([{**up["comparison"], "content_hash": "0" * 64}]), "INPUT_HASH_MISMATCH")
    await _refused(alice, report_step([{**up["comparison"], "artifact_id": "art_missing"}]), "INPUT_NOT_FOUND")
    await _refused(alice, report_step(all_refs(up), snapshot_id="SNAP-2026-08-31"), "SNAPSHOT_MISMATCH")
    await _refused(alice, report_step(all_refs(up), semantic_config_version="3.1.0"), "SEMANTIC_VERSION_MISMATCH")
    await _refused(alice, report_step(all_refs(up), operation="publish"), "UNKNOWN_OPERATION")


async def test_cross_user_and_cross_dataset_inputs(alice: McpPort, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    other = await full_upstream(alice, tmp_path / "again")
    await _refused(alice, report_step([up["insight"], up["peer_definition"], up["comparison"], other["chart_specs"][0]]), "LINEAGE_MISMATCH")
    bob = alice.as_user(BOB).as_agent("report")
    report = await run_step(report_step([up["comparison"]], user_context={"user_id": BOB, "authorized_scope": {"project_ids": ["PRJ-Y"]}},
                                        run_id=f"t_{BOB}"), bob)
    assert report.error is not None and report.error.code == "INPUT_NOT_FOUND"


async def test_broken_chart_binding_blocks_a_valid_report(alice: McpPort, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    spec = await alice.call("artifact_get", {"artifact_id": up["chart_specs"][0]["artifact_id"]})
    payload = json.loads(json.dumps(spec["payload"]))
    payload["bindings"][0]["value_exact"] = "999999"  # no longer what the source says
    draft = {k: spec[k] for k in ("artifact_type", "schema_version", "status", "producer", "snapshot_refs",
                                  "semantic_config_version", "source_refs", "input_artifact_refs", "limitations")}
    stored = await alice.as_agent("chart").call("artifact_put", {"draft_json": json.dumps({**draft, "payload": payload})})
    bad = {"artifact_id": stored["artifact_id"], "version": 1, "artifact_type": "chart_spec", "content_hash": stored["content_hash"]}
    await _refused(alice, report_step([up["insight"], up["peer_definition"], up["comparison"], bad]), "EVIDENCE_INVALID")


@pytest.mark.parametrize("breakage", [
    {"mark": {"type": "kpi_card", "tooltip": True}},  # the pre-WS7 KPI projection (F-01)
    {"encoding": {"label": {"field": "label"}, "value": {"field": "value"}}},
    {"$schema": "https://vega.github.io/schema/vega-lite/v5.json"},
])
async def test_malformed_vega_lite_blocks_a_valid_report(alice: McpPort, tmp_path: Path, breakage: dict[str, Any]) -> None:
    up = await full_upstream(alice, tmp_path)
    spec = await alice.call("artifact_get", {"artifact_id": up["chart_specs"][0]["artifact_id"]})
    payload = json.loads(json.dumps(spec["payload"]))
    payload["vega_lite"] = {**payload["vega_lite"], **breakage}  # bindings still exact: only the spec is broken
    draft = {k: spec[k] for k in ("artifact_type", "schema_version", "status", "producer", "snapshot_refs",
                                  "semantic_config_version", "source_refs", "input_artifact_refs", "limitations")}
    stored = await alice.as_agent("chart").call("artifact_put", {"draft_json": json.dumps({**draft, "payload": payload})})
    bad = {"artifact_id": stored["artifact_id"], "version": 1, "artifact_type": "chart_spec", "content_hash": stored["content_hash"]}
    await _refused(alice, report_step([up["insight"], up["peer_definition"], up["comparison"], bad]), "EVIDENCE_INVALID")


async def test_report_persistence_failure_writes_nothing(alice: McpPort, tmp_path: Path) -> None:
    up = await full_upstream(alice, tmp_path)
    port = alice.as_agent("report")

    class Failing:
        async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            if name == "save_report":
                from vdagent_data.steps import ToolFailure

                raise ToolFailure("error: disk full")
            return await port.call(name, args)

    report = await run_step(report_step(all_refs(up)), Failing())
    assert report.state == "failed" and report.error is not None and report.error.code == "REPORT_SAVE_FAILED"
    assert "report" not in {a["artifact_type"] for a in (await alice.call("artifact_list", {}))["artifacts"]}


# ---- evidence validator ---------------------------------------------------------------------------------------------


def test_validator_rejects_unsupported_or_mismatched_numbers() -> None:
    doc = {"art_c": {"metrics": [{"subjectValue": 138}]}}

    def lookup(source_ref: str) -> Any:
        ref, pointer = source_ref.split("#", 1)
        return resolve_pointer(doc[ref.split("@")[0]], pointer)

    ok = Statement("key_metrics", "DOM 138", "138", "art_c@1#/metrics/0/subjectValue")
    assert validate_statements([ok], lookup) == []
    assert validate_statements([Statement("key_metrics", "DOM 140", "140", None)], lookup)  # no source
    assert validate_statements([Statement("key_metrics", "DOM 140", "140", "art_c@1#/metrics/0/subjectValue")], lookup)
    assert validate_statements([Statement("key_metrics", "DOM", "138", "art_c@1#/metrics/9/subjectValue")], lookup)


# ---- plugin -----------------------------------------------------------------------------------------------------------


def test_report_llm_off_builds_an_offline_agent_and_default_still_needs_keys() -> None:
    from vdagent_report.agent import ReportAgent, build_agent
    from vdagent_sdk import PluginConfigError

    agent = build_agent({"REPORT_LLM": "off"})
    assert isinstance(agent, ReportAgent) and agent.has_llm is False
    with pytest.raises(PluginConfigError):
        build_agent({})


async def test_report_plugin_serves_stepspec_and_explains_free_text(alice: McpPort, mcp_tools: McpTools, tmp_path: Path) -> None:
    from vdagent_compare.tests.test_ws3_plugins import factory, report_of
    from vdagent_data.tests.test_agent_steps import Ctx
    from vdagent_report.agent import ReportAgent

    up = await full_upstream(alice, tmp_path)
    agent = ReportAgent(model=None, judge=None, mcp_session_factory=factory(mcp_tools, "report"), system_prompt="x", compact_prompt="y")
    ctx = Ctx(report_step(all_refs(up)).model_dump_json())
    await agent.invoke(ctx)
    assert report_of(ctx).state == "completed"
    ctx = Ctx("viết báo cáo doanh thu 2025")
    await agent.invoke(ctx)
    [(content, calls)] = ctx.steps
    assert calls == [] and "StepSpec@1" in content and "LLM" in content
