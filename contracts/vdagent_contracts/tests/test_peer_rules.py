"""Peer-group area rules (D9: net_area_m2 only; tolerance is a decimal ratio, 0.10 = 10 %)."""

from decimal import Decimal
from typing import Any

import pytest

from vdagent_contracts.peer_rules import (
    PEER_AREA_FIELD,
    PeerAreaUnavailable,
    area_tolerance_ratio,
    peer_area,
    tolerance_percent,
)


def test_peer_area_field_is_net_area() -> None:
    assert PEER_AREA_FIELD == "net_area_m2"


@pytest.mark.parametrize("raw", ["0.10", Decimal("0.1"), "0.05", '"0.10"'])
def test_tolerance_accepts_ratio_between_5_and_10_percent(raw: Any) -> None:
    assert Decimal("0.05") <= area_tolerance_ratio(raw) <= Decimal("0.10")


def test_tolerance_parses_semantic_config_value_of_sc_1() -> None:
    # re_warehouse/semantic_config.py stores the JSON string "0.10"
    assert area_tolerance_ratio('"0.10"') == Decimal("0.10")
    assert tolerance_percent(Decimal("0.10")) == Decimal("10")


@pytest.mark.parametrize("raw", ["10", "5", Decimal("10")])
def test_tolerance_rejects_percent_values(raw: Any) -> None:
    with pytest.raises(ValueError, match="ratio"):
        area_tolerance_ratio(raw)


@pytest.mark.parametrize("raw", ["0.04", "0.11", "-0.1", "0", "abc", "", None])
def test_tolerance_rejects_out_of_range_or_invalid(raw: Any) -> None:
    with pytest.raises(ValueError):
        area_tolerance_ratio(raw)


def test_tolerance_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        area_tolerance_ratio(0.1)


def test_peer_area_reads_net_area_m2() -> None:
    assert peer_area({"net_area_m2": "63.02", "area_m2": "68.50"}) == Decimal("63.02")


@pytest.mark.parametrize(
    "row",
    [
        {"area_m2": "68.50"},
        {"net_area_m2": None, "area_m2": "68.50"},
        {"net_area_m2": "", "area_m2": "68.50"},
        {"net_area_m2": "  ", "area_m2": "68.50"},
        {"net_area_m2": "n/a", "area_m2": "68.50"},
        {"net_area_m2": "0", "area_m2": "68.50"},
        {"net_area_m2": "-1", "area_m2": "68.50"},
    ],
)
def test_peer_area_never_falls_back_to_area_m2(row: dict[str, Any]) -> None:
    with pytest.raises(PeerAreaUnavailable):
        peer_area(row)


def test_peer_area_rejects_float() -> None:
    with pytest.raises(PeerAreaUnavailable):
        peer_area({"net_area_m2": 63.02})
