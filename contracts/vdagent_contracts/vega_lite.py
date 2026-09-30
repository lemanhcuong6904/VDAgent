"""Structural validation of the single-view Vega-Lite documents that Chart emits and Report/the UI render (WS7 F-01).

The check covers what makes vega-embed fail or silently draw nothing: the schema major version the frontend bundles
(v6), a real Vega-Lite mark, real encoding channels, valid field types and fields that exist in the inline data (or are
derived by a transform). It is not the full JSON schema; composition (layer/concat/facet) is not emitted and is rejected.
"""

from __future__ import annotations

from typing import Any

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"

MARKS = frozenset({"arc", "area", "bar", "boxplot", "circle", "errorband", "errorbar", "geoshape", "image", "line",
                   "point", "rect", "rule", "square", "text", "tick", "trail"})
CHANNELS = frozenset({"x", "y", "x2", "y2", "xOffset", "yOffset", "xError", "xError2", "yError", "yError2", "theta",
                      "theta2", "radius", "radius2", "longitude", "latitude", "longitude2", "latitude2", "color", "fill",
                      "stroke", "opacity", "fillOpacity", "strokeOpacity", "strokeWidth", "strokeDash", "size", "angle",
                      "shape", "text", "tooltip", "href", "description", "detail", "key", "order", "facet", "row",
                      "column"})
_LIST_CHANNELS = frozenset({"tooltip", "detail", "order"})
TYPES = frozenset({"quantitative", "temporal", "ordinal", "nominal", "geojson"})


def _derived(spec: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for step in spec.get("transform") or ():
        if not isinstance(step, dict):
            continue
        out = step.get("as")
        names.update(out if isinstance(out, list) else [out] if isinstance(out, str) else [])
        for key in ("joinaggregate", "aggregate", "window"):
            names.update(d["as"] for d in step.get(key) or () if isinstance(d, dict) and isinstance(d.get("as"), str))
    return names


def _check_def(channel: str, definition: Any, fields: set[str]) -> list[str]:
    if not isinstance(definition, dict):
        return [f"encoding.{channel} must be an object"]
    errors: list[str] = []
    if not {"field", "value", "datum", "aggregate", "condition"} & definition.keys():
        errors.append(f"encoding.{channel} needs a field, value or datum")
    field = definition.get("field")
    if field is not None and (not isinstance(field, str) or field.split(".", 1)[0] not in fields):
        errors.append(f"encoding.{channel}.field {field!r} is not in the data")
    kind = definition.get("type")
    if kind is not None and kind not in TYPES:
        errors.append(f"encoding.{channel}.type {kind!r} is not a Vega-Lite type")
    return errors


def validate_vega_lite(spec: Any) -> list[str]:
    """Return the problems of a single-view Vega-Lite spec; an empty list means it is renderable."""
    if not isinstance(spec, dict):
        return ["vega_lite must be an object"]
    errors: list[str] = []
    if spec.get("$schema") != VEGA_LITE_SCHEMA:
        errors.append(f"$schema must be {VEGA_LITE_SCHEMA}, got {spec.get('$schema')!r}")
    data = spec.get("data")
    values = data.get("values") if isinstance(data, dict) else None
    if not isinstance(values, list) or not values or not all(isinstance(v, dict) for v in values):
        errors.append("data.values must be a non-empty list of records")
        values = []
    mark = spec.get("mark")
    mark_type = mark.get("type") if isinstance(mark, dict) else mark
    if mark_type not in MARKS:
        errors.append(f"mark {mark_type!r} is not a Vega-Lite mark")
    encoding = spec.get("encoding")
    if not isinstance(encoding, dict) or not encoding:
        return [*errors, "encoding must be a non-empty object"]
    fields = {k for record in values for k in record} | _derived(spec)
    for channel, definition in encoding.items():
        if channel not in CHANNELS:
            errors.append(f"encoding channel {channel!r} is not a Vega-Lite channel")
        elif channel in _LIST_CHANNELS and isinstance(definition, list):
            for item in definition:
                errors += _check_def(channel, item, fields)
        else:
            errors += _check_def(channel, definition, fields)
    return errors
