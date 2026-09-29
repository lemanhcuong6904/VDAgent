from __future__ import annotations

from vdagent_data.semantic.loader import LAYER, load_layer


def test_layer_loads_with_version() -> None:
    layer = load_layer()
    assert layer.semantic_version == "1.3.0" and layer.dw_version == "3.1.0"
    assert {"absorption_rate", "avg_dom_unsold", "slow_moving_count"} <= set(layer.metrics)
    assert layer.metrics["absorption_rate"].formula_id == "F-ABS-01"
    assert "{cfg.overdue_threshold_days}" in layer.filters["slow_moving"].sql
    assert "unsold_days_dom" in layer.tables["fact_unit_inventory_snapshot"]
    assert layer is not LAYER and layer == LAYER  # module-level LAYER is loaded once


def test_join_graph_allowed_edges() -> None:
    assert LAYER.join_allowed("fact_unit_inventory_snapshot", "dim_unit_master")
    assert LAYER.join_allowed("dim_unit_master", "fact_unit_inventory_snapshot")  # undirected
    assert not LAYER.join_allowed("fact_sales_funnel_daily", "fact_market_macro_monthly")
    assert not LAYER.join_allowed("fact_sales_funnel_daily", "dim_project_profile")
    assert "dim_unit_master.project_key" in LAYER.join_fix("fact_sales_funnel_daily", "dim_project_profile")
    assert LAYER.join_fix("fact_sales_funnel_daily", "fact_market_macro_monthly") is None


def test_synonym_lookup_accent_insensitive() -> None:
    assert LAYER.lookup("toc do ban") == ("metric", "absorption_rate")
    assert LAYER.lookup("Tốc độ bán") == ("metric", "absorption_rate")
    assert LAYER.lookup("nhom tang") == ("dimension", "floor_band")
    assert LAYER.lookup("BÁN CHẬM") == ("filter", "slow_moving")
    assert LAYER.lookup("avg_dom_unsold") == ("metric", "avg_dom_unsold")
    assert LAYER.lookup("lợi nhuận") is None
