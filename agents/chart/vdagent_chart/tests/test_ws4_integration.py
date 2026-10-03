"""WS4: Chart consumes the real WS3 artifacts (insight, comparison, peer_definition) and persists chart_spec artifacts.

Upstream runs for real: Data (re_warehouse) → Insight + Compare, on the Backend's MCP tools. No demo artifact, no
mock upstream, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from vdagent_chart import mock_upstream
from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.stepspec import resolve_pointer, run_step
from vdagent_compare.stepspec import run_step as run_compare
from vdagent_compare.tests.test_dw_integration import compare_step, data_refs
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.reports import AgentReport
from vdagent_contracts.vega_lite import validate_vega_lite
from vdagent_data.tests.conftest import ALICE, BOB, McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_insight.settings import CONFIG_DIR, SemanticConfigRegistry, load_llm_config
from vdagent_insight.stepspec import StepEnv
from vdagent_insight.stepspec import run_step as run_insight
from vdagent_insight.store import InsightStore
from vdagent_insight.tests.test_dw_integration import insight_step

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
def no_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """The integrated path must never touch demo artifacts or the mock upstream."""

    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("synthetic/demo data used on the integrated path")

    monkeypatch.setattr(mock_upstream, "run_mock_upstream_pipeline", refuse)
    monkeypatch.setattr(mock_upstream, "build_mock_upstream", refuse)
    monkeypatch.setattr(FixtureArtifactStore, "demo", classmethod(lambda cls: refuse()))


async def upstream(port: McpPort, tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Data → Insight + Compare for A12-08; returns {type: ref} of their outputs plus the dataset ref."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    refs = await data_refs(port)
    env = StepEnv(registry=SemanticConfigRegistry(CONFIG_DIR), llm=load_llm_config(CONFIG_DIR / "llm.yaml"),
                  store=InsightStore(tmp_path / "insight.db"))
    ins = await run_insight(insight_step(refs), port.as_agent("insight"), env)
    cmp = await run_compare(compare_step(refs), port.as_agent("compare"))
    assert ins.state == cmp.state == "completed"
    out = {r.artifact_type.value: r.model_dump(mode="json") for r in [*ins.artifact_refs, *cmp.artifact_refs]}
    out["dataset"] = refs[0]
    out["metric"] = refs[1]
    out["dq"] = refs[2]
    return out


def chart_step(refs: list[dict[str, Any]], **over: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": f"t_{ALICE}", "plan_id": "pl_ws4", "step_id": "B4", "idempotency_key": "pl_ws4:B4",
        "operation": "draw_chart", "spec": {},
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X"], "zone_ids": []}},
        "snapshot_id": "SNAP-2026-09-28", "semantic_config_version": "sc-1",
        "input_refs": refs, "original_question": "Vì sao căn A12-08 bán chậm?",
    }
    fields.update(over)
    return StepSpec.model_validate(fields)


async def charts(port: McpPort, report: AgentReport) -> list[dict[str, Any]]:
    assert report.state == "completed", report
    assert report.artifact_refs and all(r.artifact_type.value == "chart_spec" for r in report.artifact_refs)
    return [await port.call("artifact_get", {"artifact_id": r.artifact_id, "version": r.version}) for r in report.artifact_refs]


def by_question(specs: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    return [s for s in specs if s["payload"]["visual_question"] == question]


async def assert_bindings_resolve(port: McpPort, spec: dict[str, Any]) -> None:
    """Every displayed value names an upstream source_ref whose value is exactly the displayed one."""
    bindings = spec["payload"]["bindings"]
    records = spec["payload"]["dataset"]["records"]
    shown = {(i, f) for i, r in enumerate(records) for f, v in r.items() if f not in ("label", "role")}
    assert {(b["record_index"], b["field"]) for b in bindings} == shown
    for b in bindings:
        ref, pointer = b["source_ref"].split("#", 1)
        artifact_id, version = ref.split("@")
        upstream_art = await port.call("artifact_get", {"artifact_id": artifact_id, "version": int(version)})
        assert str(resolve_pointer(upstream_art["payload"], pointer)) == b["value_exact"]
        assert str(records[b["record_index"]][b["field"]]) in (b["value_exact"], b["value_exact"].rstrip("0").rstrip("."))


# ---- plugin ---------------------------------------------------------------------------------------------------------


def test_chart_is_an_enabled_backend_plugin() -> None:
    for name in ("config.yaml", "config.compose.yaml"):
        plugins = yaml.safe_load((REPO / "backend" / name).read_text(encoding="utf-8"))["plugins"]
        [chart] = [p for p in plugins if p["module"] == "vdagent_chart"]
        assert chart.get("enabled", True) is True and not (chart.get("opts") or {}).get("demo")


def test_setup_registers_chart_with_demo_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import vdagent_chart

    monkeypatch.delenv("CHART_DEMO", raising=False)
    registered: dict[str, Any] = {}

    class Api:
        log = __import__("logging").getLogger("t")

        def register_agent(self, *, name: str, description: str, agent: Any) -> None:
            registered[name] = agent

    vdagent_chart.setup(Api(), {})
    assert registered["chart"].demo_enabled is False


async def test_demo_commands_are_refused_in_production(no_synthetic: None) -> None:
    from vdagent_chart.agent import ChartPluginAgent
    from vdagent_chart.service import ChartAgentService
    from vdagent_data.tests.test_agent_steps import Ctx

    agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False)
    for text in ("chart demo bar", "chart ask giá và DOM"):
        ctx = Ctx(text)
        await agent.invoke(ctx)
        [(content, calls)] = ctx.steps
        assert calls == [] and "demo" in content.lower() and "chart_" not in content


# ---- golden A12-08 --------------------------------------------------------------------------------------------------


async def test_golden_charts_from_real_ws3_artifacts(alice: McpPort, tmp_path: Path, no_synthetic: None) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["dataset"], up["metric"], up["dq"], up["insight"], up["comparison"], up["peer_definition"]]),
                            alice.as_agent("chart"))
    specs = await charts(alice, report)

    for spec in specs:
        assert spec["schema_version"] == "chart_spec@1" and spec["producer"]["agent"] == "chart"
        assert spec["snapshot_refs"] == ["SNAP-2026-09-28"] and spec["semantic_config_version"] == "sc-1"
        assert spec["input_artifact_refs"][0] == up["dataset"]  # the one Data dataset, pinned by hash
        assert up["metric"] in spec["input_artifact_refs"] and up["dq"] in spec["input_artifact_refs"]
        assert spec["payload"]["vega_lite"]["$schema"].startswith("https://vega.github.io/schema/vega-lite/")
        assert validate_vega_lite(spec["payload"]["vega_lite"]) == []  # WS7 F-01: renderable, not just $schema
        assert spec["payload"]["vega_lite"]["title"] == spec["payload"]["title"] and "VHop" not in json.dumps(spec)  # F-09
        assert spec["payload"]["lineage"]["metric_artifact_refs"] == [f"{up['metric']['artifact_id']}@{up['metric']['version']}"]
        assert all(b.get("metric_artifact_ref") == spec["payload"]["lineage"]["metric_artifact_refs"][0]
                   for b in spec["payload"]["bindings"])
        await assert_bindings_resolve(alice, spec)

    peer = {s["payload"]["dataset"]["comparison_metric"]: s for s in by_question(specs, "target_vs_peer")}
    assert [r["dom"] for r in peer["dom"]["payload"]["dataset"]["records"]] == [138, 61]
    assert [r["net_asking_price_per_m2"] for r in peer["net_asking_price_per_m2"]["payload"]["dataset"]["records"]] == [72500000, 64500000]
    assert peer["dom"]["payload"]["chart_type"] == "bar" and peer["dom"]["payload"]["dataset"]["unit"] == "days"

    [scatter] = by_question(specs, "relationship")
    pd = await alice.call("artifact_get", {"artifact_id": up["peer_definition"]["artifact_id"]})
    assert scatter["payload"]["chart_type"] == "scatter"
    assert sorted(r["label"] for r in scatter["payload"]["dataset"]["records"]) == sorted(
        ["A12-08", *(p["entityCode"] for p in pd["payload"]["peers"])])  # the ACTUAL Compare peers (B-11)

    kpis = by_question(specs, "current_value")
    exact = {b["metric_id"]: b["value_exact"] for s in kpis for b in s["payload"]["bindings"]}
    # Insight's typed evidence (insight_evidence@1): DOM only; its peer figures (spread 12.40, mart peer count 7) are
    # the DW mart's own peer set, so the peer view is Compare's price chart above, never a second Insight KPI
    assert exact == {"fact_unit_inventory_snapshot.unsold_days_dom": "138"}
    assert all(s["payload"]["chart_type"] == "kpi_card" for s in kpis)


async def test_integrated_charts_have_business_titles_and_axes_without_llm(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)

    forbidden = {"Target vs peer", "Relationship", "Label", "$P_{net}/m^2$"}
    for spec in specs:
        layout = spec["payload"]["plotly"]["layout"]
        labels = [layout["title"]["text"]]
        if "xaxis" in layout:
            labels.append(layout["xaxis"]["title"]["text"])
        if "yaxis" in layout:
            labels.append(layout["yaxis"]["title"]["text"])
        assert not forbidden.intersection(labels)

    price = next(s for s in specs if s["payload"]["dataset"].get("comparison_metric") == "net_asking_price_per_m2")
    assert price["payload"]["plotly"]["layout"]["title"]["text"] == "Giá ròng/m² của A12-08 so với trung vị 5 căn tương đồng"
    assert price["payload"]["plotly"]["layout"]["xaxis"]["title"]["text"] == "Căn hộ / benchmark"
    assert price["payload"]["plotly"]["layout"]["yaxis"]["title"]["text"] == "Giá ròng/m² (VND)"

    scatter = next(s for s in specs if s["payload"]["visual_question"] == "relationship")
    assert scatter["payload"]["plotly"]["layout"]["title"]["text"] == "Giá ròng/m² và DOM trong nhóm tương đồng"
    assert scatter["payload"]["plotly"]["layout"]["xaxis"]["title"]["text"] == "Giá ròng/m² (VND)"
    assert scatter["payload"]["plotly"]["layout"]["yaxis"]["title"]["text"] == "Thời gian trên thị trường (ngày)"


async def test_limitations_are_carried_and_nulls_never_charted(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["insight"], up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    for spec in specs:
        for code in ("METRIC_UNAVAILABLE:discount_pct", "BLOCKED:B-2_min_peer_count", "SYNTHETIC_SOURCE:net_area_m2"):
            assert code in spec["limitations"]
        assert spec["status"] == "PARTIAL"
        for record in spec["payload"]["dataset"]["records"]:
            assert "discount_pct" not in record and "inquiry_leads_30d" not in record
    assert report.partial is True


@pytest.mark.skip(reason="B-11 BLOCKED: the 7-peer golden chart needs an approved peer rule; charts use Compare's actual 5 peers")
async def test_golden_seven_peer_chart(alice: McpPort, tmp_path: Path) -> None:
    raise AssertionError("pending B-11")


async def test_insight_only_mode(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["insight"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    assert {s["payload"]["visual_question"] for s in specs} == {"current_value"}
    assert "UPSTREAM_MISSING:comparison" in report.warnings


async def test_compare_only_mode(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    assert {s["payload"]["visual_question"] for s in specs} == {"target_vs_peer", "relationship"}
    assert "UPSTREAM_MISSING:insight" in report.warnings


# ---- negative -------------------------------------------------------------------------------------------------------


async def _rejected(port: McpPort, step: StepSpec, code: str) -> None:
    report = await run_step(step, port.as_agent("chart"))
    assert report.state in ("rejected", "failed") and report.error is not None, report
    assert report.error.code == code
    kinds = {a["artifact_type"] for a in (await port.call("artifact_list", {}))["artifacts"]}
    assert "chart_spec" not in kinds


async def test_invalid_id_wrong_hash_and_missing_inputs(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    await _rejected(alice, chart_step([{**up["comparison"], "artifact_id": "art_missing"}]), "INPUT_NOT_FOUND")
    await _rejected(alice, chart_step([{**up["comparison"], "content_hash": "0" * 64}]), "INPUT_HASH_MISMATCH")
    await _rejected(alice, chart_step([up["dataset"]]), "MISSING_INPUT")
    await _rejected(alice, chart_step([up["insight"], up["comparison"], up["peer_definition"]], operation="plot"), "UNKNOWN_OPERATION")
    await _rejected(alice, chart_step([up["insight"]], spec={"chart_type": "radar"}), "UNSUPPORTED_CHART_TYPE")


async def test_snapshot_and_semantic_mismatch(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    refs = [up["insight"], up["comparison"], up["peer_definition"]]
    await _rejected(alice, chart_step(refs, snapshot_id="SNAP-2026-08-31"), "SNAPSHOT_MISMATCH")
    await _rejected(alice, chart_step(refs, semantic_config_version="3.1.0"), "SEMANTIC_VERSION_MISMATCH")


async def test_cross_user_reference_is_not_found(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    bob = alice.as_user(BOB).as_agent("chart")
    step = chart_step([up["comparison"]], user_context={"user_id": BOB, "authorized_scope": {"project_ids": ["PRJ-Y"]}},
                      run_id=f"t_{BOB}")
    report = await run_step(step, bob)
    assert report.error is not None and report.error.code == "INPUT_NOT_FOUND"


async def test_inputs_from_different_datasets_are_rejected(alice: McpPort, tmp_path: Path) -> None:
    first = await upstream(alice, tmp_path)
    second = await upstream(alice, tmp_path / "again")
    await _rejected(alice, chart_step([first["insight"], second["comparison"], second["peer_definition"]]), "LINEAGE_MISMATCH")
    await _rejected(alice, chart_step([first["dataset"], second["comparison"], second["peer_definition"]]), "LINEAGE_MISMATCH")


async def test_an_invalid_evidence_value_is_rejected_never_zeroed(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    ins = await alice.call("artifact_get", {"artifact_id": up["insight"]["artifact_id"]})
    payload = json.loads(json.dumps(ins["payload"]))
    payload["evidence"]["findings"][0]["metrics"][0]["value_exact"] = "n/a"
    draft = {k: ins[k] for k in ("artifact_type", "schema_version", "status", "producer", "snapshot_refs",
                                 "semantic_config_version", "source_refs", "input_artifact_refs", "evidence_refs", "limitations")}
    stored = await alice.as_agent("insight").call("artifact_put", {"draft_json": json.dumps({**draft, "payload": payload})})
    ref = {"artifact_id": stored["artifact_id"], "version": 1, "artifact_type": "insight", "content_hash": stored["content_hash"]}
    report = await run_step(chart_step([ref, up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    assert any(w.startswith("INSIGHT_EVIDENCE_INVALID:") for w in report.warnings)
    specs = await charts(alice, report)
    assert all(b["value_exact"] != "n/a" for s in specs for b in s["payload"]["bindings"])
    assert all(0 not in r.values() for s in specs for r in s["payload"]["dataset"]["records"])


async def test_chart_plugin_serves_stepspec_over_mcp(alice: McpPort, mcp_tools: Any, tmp_path: Path, no_synthetic: None) -> None:
    from vdagent_chart.agent import ChartPluginAgent
    from vdagent_chart.service import ChartAgentService
    from vdagent_compare.tests.test_ws3_plugins import factory, report_of
    from vdagent_data.tests.test_agent_steps import Ctx

    up = await upstream(alice, tmp_path)
    agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([])), demo_enabled=False,
                             mcp_session_factory=factory(mcp_tools, "chart"))
    ctx = Ctx(chart_step([up["insight"], up["comparison"], up["peer_definition"]]).model_dump_json())
    await agent.invoke(ctx)
    report = report_of(ctx)
    assert report.state == "completed" and {r.artifact_type.value for r in report.artifact_refs} == {"chart_spec"}


async def test_a_malformed_vega_lite_projection_is_never_stored(alice: McpPort, tmp_path: Path, no_synthetic: None,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """WS7 F-01 regression: the pre-fix projection (mark `kpi_card`, channels label/value/reference) must be refused."""
    from vdagent_chart import service as chart_service

    def broken(spec: dict[str, Any]) -> dict[str, Any]:
        return {"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "data": {"values": spec["dataset"]["records"]},
                "mark": {"type": "kpi_card"}, "encoding": {"label": {"field": "label"}, "value": {"field": "value"}}}

    up = await upstream(alice, tmp_path)
    monkeypatch.setattr(chart_service, "render_vega", broken)
    report = await run_step(chart_step([up["insight"], up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    assert report.state == "failed" and report.artifact_refs == []
    assert report.error is not None and "INVALID_VEGA_LITE" in report.error.message
