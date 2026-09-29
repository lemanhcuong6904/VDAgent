"""Catalog registry (build spec 01 §5): real Data/Insight catalogs, stubs for agents without a spec (DEC-020)."""

from __future__ import annotations

from vdagent_contracts.intents import TaskKind
from vdagent_orchestrator.catalogs import CatalogRegistry


def test_registry_loads_real_and_stub_catalogs() -> None:
    registry = CatalogRegistry.load()
    assert set(registry.catalogs) == {"data", "compare", "insight", "chart", "report"}
    assert not registry.catalogs["data"].fixture and not registry.catalogs["insight"].fixture
    assert registry.catalogs["compare"].fixture  # stub until the Compare spec arrives
    assert registry.served_kinds() >= {TaskKind.LOOKUP, TaskKind.EXPLAIN, TaskKind.COMPARE}
    assert TaskKind.TREND not in registry.served_kinds()
    op = registry.operation("insight", "explain_slow_moving")
    assert op.requires == ["unit_set", "metric_table"]
    assert registry.producers_of("unit_set") == [("data", "fetch_units")]


def test_registry_cached_by_version() -> None:
    first, second = CatalogRegistry.load(), CatalogRegistry.load()
    assert first is second  # same versions → same object
    assert first.versions()["data"] == "1.3.0" and first.versions()["insight"] == "2.0.0"


def test_vocab_enums_from_data_catalog() -> None:
    vocab = CatalogRegistry.load().vocabulary()
    assert "avg_dom_unsold" in vocab["metrics"] and "floor_band" in vocab["dimensions"]
    assert "slow_moving" in vocab["filters"] and "unit_code" in vocab["attributes"]
