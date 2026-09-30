"""Build the semantic artifact; renderers consume this contract, not business data."""
from __future__ import annotations
from typing import Any


def build_encoding(chart_type: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe fields semantically; the Vega adapter only projects this mapping."""
    names = list(records[0]) if records else []
    numeric = [
        name
        for name in names
        if any(isinstance(record.get(name), (int, float)) for record in records)
    ]
    dimensions = [name for name in names if name not in numeric]
    x = next(
        (name for name in names if name in {"month", "label", "status", "stage", "bin_start", "area", "project"}),
        names[0] if names else "label",
    )
    y = next(
        (
            name
            for name in names
            if name not in {x, "unit_id", "order", "bin_end"}
            and isinstance(records[0].get(name), (int, float))
        ),
        "value",
    )
    if chart_type == "kpi_card":
        return {
            "label": {"field": next((name for name in dimensions if name == "label"), "label")},
            "value": {"field": next((name for name in numeric if name not in {"reference", "target"}), "value")},
            "reference": {"field": next((name for name in numeric if name in {"reference", "target", "peer_aggregate"}), "reference")},
        }
    if chart_type == "pie":
        return {"theta": {"field": y, "type": "quantitative"}, "color": {"field": x, "type": "nominal"}}
    if chart_type in {"grouped_bar", "stacked_bar"}:
        return {
            "x": {"field": x, "type": "nominal"},
            "y": {"field": y, "type": "quantitative"},
            "series": {"field": next((name for name in dimensions if name != x), "series"), "type": "nominal"},
        }
    if chart_type == "heatmap":
        return {
            "x": {"field": "month", "type": "ordinal"},
            "y": {"field": "area", "type": "nominal"},
            "color": {"field": y, "type": "quantitative"},
        }
    if chart_type == "map":
        return {
            "lat": {"field": "lat", "type": "quantitative"},
            "lon": {"field": "lon", "type": "quantitative"},
            "color": {"field": next((name for name in numeric if name not in {"lat", "lon"}), "value"), "type": "quantitative"},
        }
    if chart_type == "scatter":
        return {
            "x": {"field": "price_m2" if "price_m2" in names else numeric[0], "type": "quantitative"},
            "y": {"field": "dom" if "dom" in names else numeric[1], "type": "quantitative"},
            **({"detail": {"field": "unit_id", "type": "nominal"}} if "unit_id" in names else {}),
        }
    if chart_type == "box_plot":
        return {
            "x": {"field": next((name for name in dimensions if name != "unit_id"), x), "type": "nominal"},
            "y": {"field": y, "type": "quantitative"},
        }
    if chart_type == "waterfall":
        return {
            "x": {"field": next((name for name in dimensions if name != "measure"), "label"), "type": "nominal"},
            "y": {"field": y, "type": "quantitative"},
            "measure": {"field": "measure", "type": "nominal"},
        }
    if chart_type == "treemap":
        return {
            "path": [name for name in ("project", "area", "property_type") if name in names] or dimensions[:2],
            "value": {"field": y, "type": "quantitative"},
        }
    if chart_type == "bullet":
        return {
            "label": {"field": next((name for name in dimensions if name == "label"), "label")},
            "value": {"field": next((name for name in numeric if name in {"actual", "value"}), "actual")},
            "target": {"field": next((name for name in numeric if name == "target"), "target")},
        }
    if chart_type == "histogram" and "dom" in names and "count" not in names:
        return {"x": {"field": "dom", "type": "quantitative"}}
    return {
        "x": {"field": x, "type": "temporal" if x == "month" else "nominal"},
        "y": {"field": y, "type": "quantitative"},
    }


def build_semantic_spec(*, chart_id: str, task_id: str, target_id: str, chart_type: str, purpose: str,
                        visual_question: str, scope: dict[str, Any], dataset: dict[str, Any],
                        selection: dict[str, Any], presentation: dict[str, Any], lineage: dict[str, Any],
                        validation: dict[str, Any], limitations: list[str] | None = None) -> dict[str, Any]:
    return {"schema_version": "chart-spec/2.0", "chart_id": chart_id, "task_id": task_id,
            "visual_target_ids": [target_id], "status": "validated", "chart_type": chart_type,
            "purpose": purpose, "visual_question": visual_question, "scope": scope, "dataset": dataset,
            "encoding": build_encoding(chart_type, list(dataset.get("records", ()))), "selection": selection, "presentation": presentation, "lineage": lineage,
            "validation": validation, "limitations": limitations or [], "governance": {"validator_version": "demo/1"}}
