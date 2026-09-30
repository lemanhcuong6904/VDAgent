"""F-01: a chart spec is validated as a whole Vega-Lite document, not only by its $schema prefix."""

from __future__ import annotations

import pytest

from vdagent_contracts.vega_lite import VEGA_LITE_SCHEMA, validate_vega_lite


def _spec(**over: object) -> dict:
    spec = {"$schema": VEGA_LITE_SCHEMA, "title": "DOM", "data": {"values": [{"label": "A12-08", "value": 138}]},
            "mark": {"type": "bar", "tooltip": True},
            "encoding": {"x": {"field": "label", "type": "nominal"}, "y": {"field": "value", "type": "quantitative"}}}
    spec.update(over)
    return spec


def test_schema_is_vega_lite_v6() -> None:
    assert VEGA_LITE_SCHEMA == "https://vega.github.io/schema/vega-lite/v6.json"


def test_a_complete_spec_is_valid() -> None:
    assert validate_vega_lite(_spec()) == []
    assert validate_vega_lite(_spec(mark="text", encoding={"text": {"field": "value", "type": "quantitative"}})) == []


@pytest.mark.parametrize(("over", "needle"), [
    ({"mark": {"type": "kpi_card"}}, "mark"),
    ({"mark": "grouped_bar"}, "mark"),
    ({"mark": None}, "mark"),
    ({"encoding": {"label": {"field": "label"}, "value": {"field": "value"}}}, "channel"),
    ({"encoding": {"x": {"field": "nope", "type": "nominal"}}}, "nope"),
    ({"encoding": {"x": {"field": "label", "type": "fancy"}}}, "type"),
    ({"encoding": {"x": "label"}}, "x"),
    ({"$schema": "https://vega.github.io/schema/vega-lite/v5.json"}, "$schema"),
    ({"data": {"values": []}}, "data"),
    ({"data": None}, "data"),
])
def test_malformed_specs_are_rejected(over: dict, needle: str) -> None:
    errors = validate_vega_lite(_spec(**over))
    assert errors and any(needle in e for e in errors), errors


def test_fields_from_transforms_and_non_dict_are_handled() -> None:
    spec = _spec(transform=[{"calculate": "datum.value * 2", "as": "double"}],
                 encoding={"x": {"field": "double", "type": "quantitative"}, "tooltip": [{"field": "label", "type": "nominal"}]})
    assert validate_vega_lite(spec) == []
    assert validate_vega_lite("not a spec") != []  # type: ignore[arg-type]
