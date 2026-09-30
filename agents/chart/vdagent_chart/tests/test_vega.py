from __future__ import annotations

import unittest

from vdagent_chart.vega import build_vega_spec


def test_renderer_projection_is_derived_from_semantic_spec():
    from vdagent_chart.vega import render_vega

    semantic_spec = {
        "schema_version": "chart-spec/2.0",
        "chart_type": "line",
        "dataset": {"records": [{"month": "2026-01", "value": 10}]},
        "presentation": {"title": "Monthly value"},
    }

    rendered = render_vega(semantic_spec)

    assert rendered["title"] == "Monthly value"
    assert rendered["data"]["values"] == [{"month": "2026-01", "value": 10}]
    assert rendered["mark"]["type"] == "line"


class VegaTests(unittest.TestCase):
    def test_builds_declarative_line_spec_without_business_logic(self) -> None:
        spec = build_vega_spec("line", [{"month": "2026-01", "price_m2": 68.0}], "Price trend")
        self.assertEqual(spec["mark"], {"type": "line", "tooltip": True})
        self.assertEqual(spec["encoding"]["x"]["field"], "month")

    def test_builds_centered_ordered_funnel_projection(self) -> None:
        spec = build_vega_spec(
            "funnel",
            [
                {"stage": "Visit", "order": 1, "count": 520},
                {"stage": "Booking", "order": 2, "count": 180},
                {"stage": "Deposit", "order": 3, "count": 104},
                {"stage": "Contract", "order": 4, "count": 82},
            ],
            "Sales funnel",
        )

        self.assertEqual(spec["mark"], {"type": "bar", "tooltip": True})
        self.assertEqual(spec["encoding"]["y"]["field"], "stage")
        self.assertEqual(spec["encoding"]["y"]["sort"], {"field": "order", "order": "ascending"})
        self.assertEqual(spec["encoding"]["x"]["field"], "center_offset")
        self.assertEqual(spec["encoding"]["x2"]["field"], "funnel_end")
        self.assertIn({"joinaggregate": [{"op": "max", "field": "count", "as": "max_count"}]}, spec["transform"])
        self.assertIn({"calculate": "(datum.max_count - datum.count) / 2", "as": "center_offset"}, spec["transform"])


# ---- WS7 F-01 / F-09: every allowed chart type projects to a renderable Vega-Lite v6 document ----------------------
import pytest  # noqa: E402

from vdagent_chart.policy import load_policy  # noqa: E402
from vdagent_contracts.vega_lite import VEGA_LITE_SCHEMA, validate_vega_lite  # noqa: E402

_RECORDS = {
    "kpi_card": [{"label": "A12-08", "value": 138, "reference": 61}],
    "bullet": [{"label": "A12-08", "actual": 138, "target": 61}],
    "grouped_bar": [{"label": "A", "series": "s1", "value": 1}, {"label": "A", "series": "s2", "value": 2}],
    "stacked_bar": [{"label": "A", "series": "s1", "value": 1}, {"label": "A", "series": "s2", "value": 2}],
    "scatter": [{"unit_id": "A12-08", "price_m2": 72.5, "dom": 138}, {"unit_id": "B", "price_m2": 64.5, "dom": 61}],
    "heatmap": [{"month": "2026-01", "area": "N", "value": 3}],
    "map": [{"lat": 10.8, "lon": 106.7, "value": 3}],
    "funnel": [{"stage": "Visit", "order": 1, "count": 520}, {"stage": "Deal", "order": 2, "count": 80}],
    "waterfall": [{"label": "start", "measure": "absolute", "value": 5}, {"label": "d", "measure": "relative", "value": -1}],
    "treemap": [{"project": "P1", "area": "N", "value": 3}],
    "box_plot": [{"project": "P1", "unit_id": "u1", "value": 3}, {"project": "P1", "unit_id": "u2", "value": 5}],
}


@pytest.mark.parametrize("chart_type", load_policy("chart-policy/demo-1.0").allowed_chart_types)
def test_every_allowed_chart_type_renders_valid_vega_lite(chart_type: str) -> None:
    from vdagent_chart.spec_builder import build_encoding
    from vdagent_chart.vega import render_vega

    records = _RECORDS.get(chart_type, [{"label": "A", "month": "2026-01", "value": 10}, {"label": "B", "month": "2026-02", "value": 12}])
    semantic = {"chart_type": chart_type, "dataset": {"records": records}, "presentation": {"title": "Tiêu đề"},
                "encoding": build_encoding(chart_type, records)}
    rendered = render_vega(semantic)
    assert rendered["$schema"] == VEGA_LITE_SCHEMA
    assert validate_vega_lite(rendered) == [], (chart_type, rendered)
    assert rendered["title"] == "Tiêu đề"


def test_kpi_card_is_a_text_mark_showing_the_value() -> None:
    from vdagent_chart.spec_builder import build_encoding
    from vdagent_chart.vega import render_vega

    records = _RECORDS["kpi_card"]
    rendered = render_vega({"chart_type": "kpi_card", "dataset": {"records": records}, "presentation": {"title": "DOM"},
                            "encoding": build_encoding("kpi_card", records)})
    assert rendered["mark"]["type"] == "text"
    assert rendered["encoding"]["text"]["field"] == "value"


def test_text_projection_has_a_fixed_height() -> None:
    """A discrete y with a container-sized view makes Vega-Lite drop fit-y with a console warning (WS7 browser run)."""
    from vdagent_chart.spec_builder import build_encoding
    from vdagent_chart.vega import render_vega

    records = [{"label": "A12-08", "value": 138}, {"label": "Trung vị", "value": 61}]
    rendered = render_vega({"chart_type": "kpi_card", "dataset": {"records": records}, "presentation": {"title": "DOM"},
                            "encoding": build_encoding("kpi_card", records)})
    assert isinstance(rendered["height"], int) and rendered["height"] >= 40 * 2
