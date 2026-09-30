"""Fixture-backed ship gate: every documented demo has a safe render artifact."""

import pytest
import json
from pathlib import Path

from vdagent_chart.fixture_store import FixtureArtifactStore
from vdagent_chart.fixtures import load_demo_task, scenario_names
from vdagent_chart.output_validation import validate_chart_spec
from vdagent_chart.service import ChartAgentService

ARTIFACTS_FILE = Path(__file__).parents[1] / "demo" / "artifacts.json"


@pytest.mark.parametrize(
    ("scenario", "expected_chart_type", "expected_trace_type"),
    [
        ("kpi_card", "kpi_card", "indicator"),
        ("line", "line", "scatter"),
        ("area", "area", "scatter"),
        ("bar", "bar", "bar"),
        ("grouped_bar", "grouped_bar", "bar"),
        ("stacked_bar", "stacked_bar", "bar"),
        ("pie", "pie", "pie"),
        ("scatter", "scatter", "scatter"),
        ("histogram", "histogram", "bar"),
        ("box_plot", "box_plot", "box"),
        ("heatmap", "heatmap", "heatmap"),
        ("map", "map", "scattermap"),
        ("funnel", "funnel", "funnel"),
        ("waterfall", "waterfall", "waterfall"),
        ("treemap", "treemap", "treemap"),
        ("bullet", "bullet", "indicator"),
    ],
)
def test_documented_demo_scenario_produces_valid_semantic_spec_and_renderer_projection(
    scenario: str, expected_chart_type: str, expected_trace_type: str
):
    service = ChartAgentService(FixtureArtifactStore.demo())

    result = service.execute(load_demo_task(scenario))

    assert result.status == "success"
    artifact_id = result.chart_artifacts[0].removesuffix("@1")
    artifact = service.artifacts[artifact_id]
    assert validate_chart_spec(artifact["semantic_spec"])["overall_result"] == "pass"
    assert artifact["semantic_spec"]["validation"]["checks"] == [
        "schema",
        "lineage",
        "dataset",
        "scope",
        "renderer",
        "presentation",
    ]
    assert artifact["render_spec"]["renderer"] == "plotly"
    assert artifact["render_spec"]["data"]
    assert artifact["semantic_spec"]["chart_type"] == expected_chart_type
    assert artifact["render_spec"]["data"][0]["type"] == expected_trace_type
    assert artifact["semantic_spec"]["vega_render_spec"]["data"]["values"] == artifact["dataset"]["records"]


def test_documented_demo_catalog_covers_all_supported_chart_types() -> None:
    assert set(
        [
            "kpi_card",
            "line",
            "area",
            "bar",
            "grouped_bar",
            "stacked_bar",
            "pie",
            "scatter",
            "histogram",
            "box_plot",
            "heatmap",
            "map",
            "funnel",
            "waterfall",
            "treemap",
            "bullet",
        ]
    ).issubset(set(scenario_names()))


def test_demo_fixtures_include_rich_synthetic_insight_and_comparison_context() -> None:
    artifacts = json.loads(ARTIFACTS_FILE.read_text(encoding="utf-8"))["artifacts"]
    synthetic = [
        artifact
        for artifact in artifacts
        if artifact["artifact_id"].startswith(("insight_synthetic_", "comparison_synthetic_"))
    ]

    assert len([artifact for artifact in synthetic if artifact["artifact_type"] == "insight"]) >= 6
    assert len([artifact for artifact in synthetic if artifact["artifact_type"] == "comparison"]) >= 4
    assert all(artifact["payload"].get("chart_plan_seed") for artifact in synthetic)


def test_rich_context_demo_preserves_upstream_insight_and_comparison_lineage() -> None:
    service = ChartAgentService(FixtureArtifactStore.demo())

    result = service.execute(load_demo_task("rich_context_relationship"))

    assert result.status == "success"
    artifact = service.artifacts[result.chart_artifacts[0].removesuffix("@1")]
    refs = set(artifact["lineage"])
    assert "insight_synthetic_price_dom@1" in refs
    assert "comparison_synthetic_price_dom_segments@1" in refs
    assert artifact["semantic_spec"]["chart_type"] == "scatter"


def test_documented_missing_dependency_returns_only_a_dependency_request():
    result = ChartAgentService(FixtureArtifactStore.demo()).execute(load_demo_task("missing_dependency"))

    assert result.status == "failed"
    assert result.chart_artifacts == ()
    assert result.dependency_requests == ({"artifact_id": "metric_not_ready", "version": 1, "code": "DEP-002"},)


def test_sales_funnel_demo_uses_funnel_projection_not_plain_vertical_bar():
    service = ChartAgentService(FixtureArtifactStore.demo())

    result = service.execute(load_demo_task("sales_funnel"))

    artifact = service.artifacts[result.chart_artifacts[0].removesuffix("@1")]
    render_spec = artifact["render_spec"]
    assert render_spec["renderer"] == "plotly"
    assert render_spec["data"][0]["type"] == "funnel"
    assert render_spec["data"][0]["y"] == ["Visit", "Booking", "Deposit", "Contract"]
    assert render_spec["data"][0]["x"] == [520, 180, 104, 82]

    vega_render_spec = artifact["semantic_spec"]["vega_render_spec"]
    assert vega_render_spec["encoding"]["y"]["field"] == "stage"
    assert vega_render_spec["encoding"]["x"]["field"] == "center_offset"
    assert vega_render_spec["encoding"]["x2"]["field"] == "funnel_end"
    assert {"calculate": "datum.center_offset + datum.count", "as": "funnel_end"} in vega_render_spec["transform"]
