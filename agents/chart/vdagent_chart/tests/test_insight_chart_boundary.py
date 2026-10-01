"""Insight → Chart boundary, consumer side (`insight_evidence@1`): Chart draws Insight's typed evidence only — never the
narrative, never a value the Data dataset does not hold — and leaves peer comparisons to Compare.

Upstream runs for real (Data → Insight + Compare on the mock DW); a tampered artifact is written with the producing
agent's own identity, as a buggy producer would.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from vdagent_chart.stepspec import resolve_pointer, run_step
from vdagent_chart.tests.test_ws4_integration import assert_bindings_resolve, by_question, chart_step, charts, upstream
from vdagent_contracts.insight_evidence import parse_evidence
from vdagent_data.tests.conftest import McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)

DOM = "fact_unit_inventory_snapshot.unsold_days_dom"
PRICE = "fact_unit_inventory_snapshot.net_price_per_m2"
PEERS = "dm_unit_friction_diagnostics.peer_n"


async def get(port: McpPort, ref: dict[str, Any]) -> dict[str, Any]:
    return await port.call("artifact_get", {"artifact_id": ref["artifact_id"], "version": ref["version"]})


async def rewrite(port: McpPort, ref: dict[str, Any], agent: str, change: Any) -> dict[str, Any]:
    """Store a copy of an artifact whose payload `change` edited, as `agent` (its producer) would."""
    env = await get(port, ref)
    payload = copy.deepcopy(env["payload"])
    change(payload)
    draft = {k: env[k] for k in ("artifact_type", "schema_version", "status", "producer", "snapshot_refs",
                                 "semantic_config_version", "source_refs", "input_artifact_refs", "evidence_refs", "limitations")}
    stored = await port.as_agent(agent).call("artifact_put", {"draft_json": json.dumps({**draft, "payload": payload})})
    return {"artifact_id": stored["artifact_id"], "version": stored["version"], "artifact_type": ref["artifact_type"],
            "content_hash": stored["content_hash"]}


def facts(specs: list[dict[str, Any]]) -> list[Any]:
    """What a chart shows and stands on (everything but the artifact id): stable across identical inputs."""
    keys = ("visual_question", "chart_type", "title", "dataset", "bindings", "vega_lite", "plotly", "lineage")
    return sorted(json.dumps({k: s["payload"].get(k) for k in keys}, sort_keys=True) for s in specs)


def kpi_metrics(specs: list[dict[str, Any]]) -> dict[str, str]:
    return {b["metric_id"]: b["value_exact"] for s in by_question(specs, "current_value") for b in s["payload"]["bindings"]}


async def test_kpis_come_from_the_typed_evidence_with_lineage_to_the_finding_and_the_dataset(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["insight"], up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    insight = await get(alice, up["insight"])
    evidence = parse_evidence(insight["payload"])

    assert kpi_metrics(specs) == {DOM: "138"}  # 12.40 / 7 are the DW mart's peer figures: Compare owns peer views
    for spec in by_question(specs, "current_value"):
        await assert_bindings_resolve(alice, spec)  # the KPI value is the dataset's value
        for b in spec["payload"]["bindings"]:
            assert b["source_ref"].startswith(f"{up['dataset']['artifact_id']}@{up['dataset']['version']}#/tables/")
            for ref in b["evidence_refs"]:  # and Insight's evidence states the same number
                aid, _, rest = ref.partition("@")
                version, _, pointer = rest.partition("#")
                assert aid == up["insight"]["artifact_id"] and int(version) == up["insight"]["version"]
                assert resolve_pointer(insight["payload"], pointer) == b["value_exact"]
            assert set(b["finding_ids"]) <= {f.finding_id for f in evidence.findings} and b["finding_ids"]
        assert spec["payload"]["lineage"]["insight"] == f"{up['insight']['artifact_id']}@{up['insight']['version']}"

    [overpriced] = [f for f in evidence.findings if f.cause_code == "OVERPRICED_VS_PEER"]
    [price] = [s for s in by_question(specs, "target_vs_peer") if s["payload"]["lineage"]["metric_ids"] == [PRICE]]
    assert overpriced.finding_id in price["payload"]["lineage"]["finding_ids"]  # Insight's peer view, drawn from Compare


async def test_chart_never_reads_the_narrative(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    original = await charts(alice, await run_step(chart_step([up["insight"]]), alice.as_agent("chart")))

    def scramble(payload: dict[str, Any]) -> None:
        for item in payload["insight"]["insights"]:
            item["claim"]["rendered_text"] = "Căn tồn 999 ngày, cao hơn peer 77%."
            for b in item["claim"]["numeric_bindings"]:
                b.update(value="999", display="999 ngày")
        payload["insight"]["chart_hints"] = []

    scrambled = await rewrite(alice, up["insight"], "insight", scramble)
    report = await run_step(chart_step([scrambled], step_id="B41", idempotency_key="pl_ws4:B41"), alice.as_agent("chart"))
    again = await charts(alice, report)
    strip = [json.loads(f) for f in facts(again)], [json.loads(f) for f in facts(original)]
    for a, b in zip(*strip, strict=True):
        a["lineage"].pop("insight"), b["lineage"].pop("insight")
        for x in (a, b):
            for binding in x["bindings"]:
                binding.pop("evidence_refs", None)
    assert strip[0] == strip[1]
    assert "999" not in json.dumps([s["payload"] for s in again])


@pytest.mark.parametrize(("change", "code"), [
    (lambda p: p.pop("evidence"), "INSIGHT_EVIDENCE_MISSING"),
    (lambda p: p["evidence"]["findings"][0]["metrics"][0].update(unit="PCT"), "INSIGHT_EVIDENCE_INVALID"),
    (lambda p: p["evidence"].update(schema_version="insight_evidence@0"), "INSIGHT_EVIDENCE_INVALID"),
])
async def test_a_missing_or_broken_evidence_block_fails_with_its_code_and_no_fallback(
        alice: McpPort, tmp_path: Path, change: Any, code: str) -> None:
    up = await upstream(alice, tmp_path)
    broken = await rewrite(alice, up["insight"], "insight", change)
    alone = await run_step(chart_step([broken]), alice.as_agent("chart"))
    assert alone.state == "failed" and alone.error is not None and alone.error.code == "NOTHING_TO_CHART"
    assert code in alone.error.message  # the reason, not a fabricated chart from the narrative

    with_compare = await run_step(chart_step([broken, up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, with_compare)
    assert any(w.startswith(code) for w in with_compare.warnings)
    assert {s["payload"]["visual_question"] for s in specs} == {"target_vs_peer", "relationship"}  # Compare's only


async def test_an_evidence_value_or_pointer_the_dataset_does_not_back_is_never_charted(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)

    def wrong_value(payload: dict[str, Any]) -> None:
        for f in payload["evidence"]["findings"]:
            for m in f["metrics"]:
                if m["metric_id"] == DOM:
                    m["value_exact"] = "139"

    def dangling(payload: dict[str, Any]) -> None:
        for f in payload["evidence"]["findings"]:
            for m in f["metrics"]:
                if m["metric_id"] == DOM:
                    m["source_ref"] = m["source_ref"].rsplit("/", 2)[0] + "/9999/unsold_days_dom"

    for change, code in ((wrong_value, "EVIDENCE_VALUE_MISMATCH"), (dangling, "EVIDENCE_UNRESOLVED")):
        bad = await rewrite(alice, up["insight"], "insight", change)
        report = await run_step(chart_step([bad, up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
        specs = await charts(alice, report)
        assert any(w.startswith(f"{code}:") and DOM in w for w in report.warnings)
        assert DOM not in kpi_metrics(specs)  # no KPI from Insight's dom: one truth, the dataset's
        assert "139" not in json.dumps([s["payload"]["dataset"] for s in specs])


async def test_a_compare_value_the_dataset_does_not_back_is_never_charted(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)

    def wrong_dom(payload: dict[str, Any]) -> None:
        for m in payload["metrics"]:
            if m["metric"] == "dom":
                m["subjectValue"] = 139

    bad = await rewrite(alice, up["comparison"], "compare", wrong_dom)
    report = await run_step(chart_step([up["insight"], bad, up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    assert f"VALUE_MISMATCH_WITH_DATASET:comparison:{DOM}" in report.warnings
    peer = [s for s in by_question(specs, "target_vs_peer") if s["payload"]["lineage"]["metric_ids"] == [DOM]]
    assert peer == [] and kpi_metrics(specs) == {DOM: "138"}  # Insight's verified 138 stays; 139 never shown


async def test_a_normal_run_has_one_peer_truth_and_no_peer_basis_conflict(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["insight"], up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    assert not any(w.startswith("PEER_BASIS_DIFFERS") for w in report.warnings)
    shown = [r for s in specs for r in s["payload"]["dataset"]["records"]]
    assert all(7 not in r.values() and "7" not in r.values() for r in shown)  # the mart's 7 peers: never shown


async def test_a_stale_insight_carrying_mart_peer_figures_is_rejected_not_charted(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)

    def stale(payload: dict[str, Any]) -> None:  # what an insight_evidence@1 artifact still held
        f = next(f for f in payload["evidence"]["findings"] if f["cause_code"] == "OVERPRICED_VS_PEER")
        f["metrics"].append({"metric_id": PEERS, "slot": "peers", "label": "Số căn tương đồng (mart DW)", "value_exact": "7",
                             "unit": "COUNT", "role": "supporting", "source_ref": None, "chartable": False,
                             "not_chartable_reason": "PEER_BASIS_COMPARE_OWNS"})

    bad = await rewrite(alice, up["insight"], "insight", stale)
    report = await run_step(chart_step([bad, up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    assert any(w.startswith("INSIGHT_EVIDENCE_INVALID:") and "Compare owns peer facts" in w for w in report.warnings)
    assert {s["payload"]["visual_question"] for s in specs} == {"target_vs_peer", "relationship"}  # Compare's only
    assert all(7 not in r.values() for s in specs for r in s["payload"]["dataset"]["records"])


async def test_a_peer_view_without_a_comparison_is_explained_not_fabricated(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    report = await run_step(chart_step([up["insight"]]), alice.as_agent("chart"))
    specs = await charts(alice, report)
    assert {s["payload"]["visual_question"] for s in specs} == {"current_value"}
    assert any(w.startswith("VISUAL_NEEDS_COMPARISON:C-T1-") for w in report.warnings)


async def test_nothing_chartable_is_a_clear_failure_with_every_reason(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)

    def no_intents(payload: dict[str, Any]) -> None:
        for f in payload["evidence"]["findings"]:
            f["visual_intents"] = []

    bare = await rewrite(alice, up["insight"], "insight", no_intents)
    report = await run_step(chart_step([bare]), alice.as_agent("chart"))
    assert report.state == "failed" and report.error is not None and report.error.code == "NOTHING_TO_CHART"
    assert "NO_VISUAL_INTENT:C-T1-" in report.error.message
    kinds = {a["artifact_type"] for a in (await alice.call("artifact_list", {}))["artifacts"]}
    assert "chart_spec" not in kinds


async def test_identical_inputs_give_identical_chart_specs(alice: McpPort, tmp_path: Path) -> None:
    up = await upstream(alice, tmp_path)
    refs = [up["insight"], up["comparison"], up["peer_definition"]]
    first = await charts(alice, await run_step(chart_step(refs), alice.as_agent("chart")))
    second = await charts(alice, await run_step(chart_step(refs, step_id="B42", idempotency_key="pl_ws4:B42"), alice.as_agent("chart")))
    assert facts(first) == facts(second)


async def test_the_product_path_never_lets_an_llm_change_question_type_or_title(alice: McpPort, mcp_tools: Any, tmp_path: Path) -> None:
    from vdagent_chart.agent import ChartPluginAgent
    from vdagent_chart.fixture_store import FixtureArtifactStore
    from vdagent_chart.service import ChartAgentService
    from vdagent_compare.tests.test_ws3_plugins import factory, report_of
    from vdagent_data.tests.test_agent_steps import Ctx

    class Meddler:
        calls = 0

        async def decide(self, payload: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
            Meddler.calls += 1
            return {"visual_question": {"type": "distribution"}, "selection": {"chart_type": "bullet"},
                    "presentation": {"title": "Giá thuê cao hơn 99% so với nhóm"}}

        async def suggest(self, visual_question: str, allowed: tuple[str, ...]) -> str | None:
            Meddler.calls += 1
            return "bullet"

    up = await upstream(alice, tmp_path)
    refs = [up["insight"], up["comparison"], up["peer_definition"]]
    baseline = await charts(alice, await run_step(chart_step(refs), alice.as_agent("chart")))
    agent = ChartPluginAgent(ChartAgentService(FixtureArtifactStore([]), reasoner=Meddler()), upstream_reasoner=Meddler(),
                             demo_enabled=False, mcp_session_factory=factory(mcp_tools, "chart"))
    ctx = Ctx(chart_step(refs, step_id="B43", idempotency_key="pl_ws4:B43").model_dump_json())
    await agent.invoke(ctx)
    meddled = await charts(alice, report_of(ctx))
    assert Meddler.calls == 0 and facts(meddled) == facts(baseline)
    assert "99" not in json.dumps([s["payload"]["title"] for s in meddled])


async def test_every_chart_is_logged_with_its_lineage_and_no_payload(alice: McpPort, tmp_path: Path,
                                                                     caplog: pytest.LogCaptureFixture) -> None:
    up = await upstream(alice, tmp_path)
    with caplog.at_level(logging.INFO, logger="vdagent.plugin.vdagent_chart"):
        report = await run_step(chart_step([up["insight"], up["comparison"], up["peer_definition"]]), alice.as_agent("chart"))
    stored = [json.loads(r.getMessage()) for r in caplog.records if '"CHART_SPEC_STORED"' in r.getMessage()]
    assert {e["chart_artifact_id"] for e in stored} == {r.artifact_id for r in report.artifact_refs}
    insight = f"{up['insight']['artifact_id']}@{up['insight']['version']}"
    comparison = f"{up['comparison']['artifact_id']}@{up['comparison']['version']}"
    for event in stored:  # each chart names exactly what it came from
        assert event["run_id"] == f"t_{alice.identity.user_id}" and event["validation"] == "pass"
        assert event["chart_type"] and event["metric_ids"] and event["source_refs"] and event["latency_ms"] >= 0
        if event["visual_question"] == "current_value":
            assert (event["insight_artifact"], event["comparison_artifact"]) == (insight, None) and event["finding_ids"]
        else:
            assert event["comparison_artifact"] == comparison and event["insight_artifact"] in (insight, None)
            assert bool(event["finding_ids"]) == (event["insight_artifact"] == insight)
    assert any(e["visual_question"] == "target_vs_peer" and e["finding_ids"] for e in stored)  # Insight's peer view
    assert all(len(r.getMessage()) < 3000 for r in caplog.records if "CHART_" in r.getMessage())  # no payload dumps
    summary = [json.loads(r.getMessage()) for r in caplog.records if '"CHART_STEP_DONE"' in r.getMessage()]
    assert summary and summary[0]["charts"] == len(report.artifact_refs)
