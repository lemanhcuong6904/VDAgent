from __future__ import annotations

import pytest

from vdagent_chart.errors import ChartError
from vdagent_chart.rendering.plotly import RENDERERS, render_plotly


ALL_CHART_TYPES = (
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
)


def _spec(chart_type: str, records: list[dict], encoding: dict) -> dict:
    return {
        "chart_type": chart_type,
        "dataset": {"records": records},
        "encoding": encoding,
        "presentation": {"title_spec": {"format": "plain", "value": chart_type}},
    }


@pytest.mark.parametrize(
    ("chart_type", "records", "encoding", "expected_trace", "expected_layout"),
    [
        ("kpi_card", [{"label": "DOM", "value": 126, "reference": 91}], {"value": {"field": "value"}, "reference": {"field": "reference"}}, "indicator", {}),
        ("line", [{"month": "2026-01", "price_m2": 68}, {"month": "2026-02", "price_m2": 69}], {"x": {"field": "month"}, "y": {"field": "price_m2"}}, "scatter", {}),
        ("area", [{"month": "2026-01", "price_m2": 68}, {"month": "2026-02", "price_m2": 69}], {"x": {"field": "month"}, "y": {"field": "price_m2"}}, "scatter", {}),
        ("bar", [{"label": "A", "value": 10}, {"label": "B", "value": 12}], {"x": {"field": "label"}, "y": {"field": "value"}}, "bar", {}),
        ("grouped_bar", [{"area": "A01", "type": "1BR", "inventory": 30}, {"area": "A01", "type": "2BR", "inventory": 42}], {"x": {"field": "area"}, "y": {"field": "inventory"}, "series": {"field": "type"}}, "bar", {"barmode": "group"}),
        ("stacked_bar", [{"area": "A01", "type": "1BR", "inventory": 30}, {"area": "A01", "type": "2BR", "inventory": 42}], {"x": {"field": "area"}, "y": {"field": "inventory"}, "series": {"field": "type"}}, "bar", {"barmode": "stack"}),
        ("pie", [{"status": "Available", "count": 120}], {"color": {"field": "status"}, "theta": {"field": "count"}}, "pie", {}),
        ("scatter", [{"unit_id": "U01", "price_m2": 72, "dom": 32}], {"x": {"field": "price_m2"}, "y": {"field": "dom"}, "detail": {"field": "unit_id"}}, "scatter", {}),
        ("histogram", [{"dom": 32}, {"dom": 55}], {"x": {"field": "dom"}}, "histogram", {}),
        ("box_plot", [{"area": "A01", "dom": 32}, {"area": "A01", "dom": 55}], {"x": {"field": "area"}, "y": {"field": "dom"}}, "box", {}),
        ("heatmap", [{"area": "A01", "month": "2026-01", "available": 12}], {"x": {"field": "month"}, "y": {"field": "area"}, "color": {"field": "available"}}, "heatmap", {}),
        ("map", [{"lat": 10.77, "lon": 106.7, "price_m2": 72}], {"lat": {"field": "lat"}, "lon": {"field": "lon"}, "color": {"field": "price_m2"}}, "scattermap", {}),
        ("funnel", [{"stage": "Visit", "order": 1, "count": 520}], {"x": {"field": "stage"}, "y": {"field": "count"}}, "funnel", {}),
        ("waterfall", [{"label": "Base", "value": 70, "measure": "relative"}], {"x": {"field": "label"}, "y": {"field": "value"}, "measure": {"field": "measure"}}, "waterfall", {}),
        ("treemap", [{"project": "VHOP", "area": "A01", "inventory": 30}], {"path": ["project", "area"], "value": {"field": "inventory"}}, "treemap", {}),
        ("bullet", [{"label": "Sales", "actual": 82, "target": 100}], {"value": {"field": "actual"}, "target": {"field": "target"}}, "indicator", {}),
    ],
)
def test_plotly_registry_supports_all_declared_chart_types(chart_type, records, encoding, expected_trace, expected_layout):
    rendered = render_plotly(_spec(chart_type, records, encoding))

    assert set(ALL_CHART_TYPES).issubset(RENDERERS)
    assert rendered["renderer"] == "plotly"
    assert rendered["data"][0]["type"] == expected_trace
    for key, value in expected_layout.items():
        assert rendered["layout"][key] == value


def test_plotly_renderer_rejects_unknown_chart_type_instead_of_falling_back_to_bar() -> None:
    with pytest.raises(ChartError, match="unsupported chart type"):
        render_plotly(_spec("not_a_chart", [{"label": "A", "value": 1}], {"x": {"field": "label"}, "y": {"field": "value"}}))


def test_plotly_renderer_uses_presentation_math_text_and_theme() -> None:
    spec = {
        "chart_type": "scatter",
        "dataset": {
            "records": [{"unit_id": "U01", "area_m2": 72.0, "price_m2": 68.5}],
        },
        "encoding": {
            "x": {"field": "area_m2", "type": "quantitative"},
            "y": {"field": "price_m2", "type": "quantitative"},
            "detail": {"field": "unit_id", "type": "nominal"},
        },
        "presentation": {
            "title_spec": {"format": "plain", "value": "Price by area"},
            "x_axis": {"field": "area_m2", "title": {"format": "math", "value": "$S\\;(m^2)$"}},
            "y_axis": {"field": "price_m2", "title": {"format": "math", "value": "$P\\;(\\mathrm{triệu\\ VND}/m^2)$"}},
            "theme_ref": "dashboard/default",
        },
    }

    rendered = render_plotly(spec)

    assert rendered["renderer"] == "plotly"
    assert rendered["data"][0]["type"] == "scatter"
    assert rendered["data"][0]["mode"] == "markers"
    assert rendered["layout"]["title"]["text"] == "Price by area"
    assert rendered["layout"]["xaxis"]["title"]["text"] == "$S\\;(m^2)$"
    assert rendered["layout"]["yaxis"]["title"]["text"] == "$P\\;(\\mathrm{triệu\\ VND}/m^2)$"
    assert rendered["layout"]["font"]["family"] == "Inter, system-ui, sans-serif"
    assert rendered["config"]["responsive"] is True
    assert rendered["config"]["typesetMath"] is True


def test_plotly_renderer_unwraps_prose_axis_titles_that_llm_marks_as_math() -> None:
    rendered = render_plotly(
        {
            "chart_type": "scatter",
            "dataset": {
                "records": [{"dom": 138, "net_asking_price_per_m2": 72_500_000}],
            },
            "encoding": {
                "x": {"field": "dom", "type": "quantitative"},
                "y": {"field": "net_asking_price_per_m2", "type": "quantitative"},
            },
            "presentation": {
                "title_spec": {"format": "plain", "value": "Giá và thời gian trên thị trường"},
                "x_axis": {"title": {"format": "plain", "value": "Thời gian trên thị trường (ngày)"}},
                "y_axis": {"title": {"format": "math", "value": "$Giá yêu cầu ròng (VND/m^2)$"}},
            },
        }
    )

    assert rendered["layout"]["yaxis"]["title"]["text"] == "Giá yêu cầu ròng (VND/m²)"


def test_kpi_card_displays_unit_suffix_and_record_label() -> None:
    rendered = render_plotly(
        {
            "chart_type": "kpi_card",
            "dataset": {"unit": "DAY", "records": [{"label": "A12-08 · DOM", "value": 138}]},
            "encoding": {"value": {"field": "value"}},
            "presentation": {"title_spec": {"format": "plain", "value": "Thời gian bán của A12-08"}},
        }
    )

    assert rendered["data"][0]["number"]["suffix"] == " ngày"
    assert rendered["data"][0]["title"]["text"] == "A12-08 · DOM"


def test_kpi_card_displays_percent_suffix_for_price_gap() -> None:
    rendered = render_plotly(
        {
            "chart_type": "kpi_card",
            "dataset": {"unit": "PCT", "records": [{"label": "A12-08 · chênh giá peer", "value": 12.4}]},
            "encoding": {"value": {"field": "value"}},
            "presentation": {"title_spec": {"format": "plain", "value": "Chênh giá so với peer"}},
        }
    )

    assert rendered["data"][0]["number"]["suffix"] == "%"


def test_plotly_renderer_uses_dashboard_polish_defaults() -> None:
    rendered = render_plotly(
        _spec(
            "bar",
            [{"label": "A12-08", "value": 72_500_000}, {"label": "Peer median", "value": 64_500_000}],
            {"x": {"field": "label"}, "y": {"field": "value"}},
        )
    )

    assert rendered["layout"]["template"] == "plotly_white"
    assert rendered["layout"]["title"]["x"] == 0.02
    assert rendered["layout"]["colorway"][:3] == ["#2563eb", "#14b8a6", "#f97316"]
    assert rendered["layout"]["uniformtext"]["mode"] == "hide"
    assert rendered["layout"]["bargap"] == 0.32
    assert rendered["layout"]["xaxis"]["showgrid"] is False
    assert rendered["layout"]["yaxis"]["gridcolor"] == "#e2e8f0"
    assert rendered["data"][0]["marker"]["color"] == "#2563eb"
    assert rendered["data"][0]["marker"]["line"]["color"] == "#1d4ed8"


def test_single_series_chart_hides_legend_and_uses_business_trace_label() -> None:
    rendered = render_plotly(
        {
            "chart_type": "bar",
            "dataset": {"records": [{"label": "A12-08", "value": 72_500_000}]},
            "encoding": {"x": {"field": "label"}, "y": {"field": "value"}},
            "presentation": {
                "title_spec": {"format": "plain", "value": "A12-08 cao hơn trung vị peer"},
                "legend": {"title": "Chỉ số", "items": {"value": "Giá bán ròng/m²"}},
            },
        }
    )

    assert rendered["layout"]["showlegend"] is False
    assert rendered["data"][0]["name"] == "Giá bán ròng/m²"


def test_grouped_chart_shows_legend_with_business_title() -> None:
    rendered = render_plotly(
        {
            "chart_type": "grouped_bar",
            "dataset": {
                "records": [
                    {"label": "A12-08", "series": "target", "value": 72_500_000},
                    {"label": "Peer", "series": "median", "value": 64_500_000},
                ],
            },
            "encoding": {"x": {"field": "label"}, "y": {"field": "value"}, "series": {"field": "series"}},
            "presentation": {
                "title_spec": {"format": "plain", "value": "Giá A12-08 so với peer"},
                "legend": {"title": "Nhóm so sánh", "items": {"target": "A12-08", "median": "Trung vị peer"}},
            },
        }
    )

    assert rendered["layout"]["showlegend"] is True
    assert rendered["layout"]["legend"]["title"]["text"] == "Nhóm so sánh"
    assert [trace["name"] for trace in rendered["data"]] == ["A12-08", "Trung vị peer"]


def test_plotly_renderer_preserves_funnel_order_and_values() -> None:
    rendered = render_plotly(
        {
            "chart_type": "funnel",
            "dataset": {
                "records": [
                    {"stage": "Visit", "order": 1, "count": 520},
                    {"stage": "Booking", "order": 2, "count": 180},
                ],
            },
            "encoding": {"x": {"field": "stage"}, "y": {"field": "count"}},
            "presentation": {"title_spec": {"format": "plain", "value": "Sales funnel"}},
        }
    )

    assert rendered["data"][0]["type"] == "funnel"
    assert rendered["data"][0]["y"] == ["Visit", "Booking"]
    assert rendered["data"][0]["x"] == [520, 180]


def test_plotly_renderer_projects_heatmap_matrix() -> None:
    rendered = render_plotly(
        {
            "chart_type": "heatmap",
            "dataset": {
                "records": [
                    {"area": "A01", "month": "2026-01", "available": 12},
                    {"area": "A01", "month": "2026-02", "available": 10},
                    {"area": "A02", "month": "2026-01", "available": 8},
                    {"area": "A02", "month": "2026-02", "available": 7},
                ],
            },
            "encoding": {
                "x": {"field": "month", "type": "ordinal"},
                "y": {"field": "area", "type": "nominal"},
                "color": {"field": "available", "type": "quantitative"},
            },
            "presentation": {"title_spec": {"format": "plain", "value": "Inventory heatmap"}},
        }
    )

    assert rendered["data"][0]["type"] == "heatmap"
    assert rendered["data"][0]["x"] == ["2026-01", "2026-02"]
    assert rendered["data"][0]["y"] == ["A01", "A02"]
    assert rendered["data"][0]["z"] == [[12, 10], [8, 7]]
