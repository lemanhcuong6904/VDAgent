"""Visualize specialist: lets the model choose a chart from real columns, then persists it."""

from __future__ import annotations

import re
from typing import Any

from _common import (
    DATASET_ID,
    GUARDRAILS,
    PROMPT_INPUT,
    TEXT_OUTPUT,
    ask_json,
    ids,
    is_numeric,
    prompt_of,
    section,
)
from agent_platform import AgentContext, AgentManifest, serve

SYSTEM = (
    "You are the Visualize specialist. Choose one chart that makes the stated comparison or "
    "insight easy to inspect. Use only the listed columns; y must be numeric. Use a line chart "
    "for time on x, otherwise a bar chart. The title states the finding in under 12 words."
)


class VisualizeAgent:
    manifest = AgentManifest(
        id="visualize",
        version="1.0.0",
        name="Visualize",
        description="Chooses and persists charts from verified data and comparison/insight findings.",
        tools=("warehouse.describe_dataset", "warehouse.get_dataset_rows", "warehouse.create_chart"),
        capabilities=("dataset.visualize", "visualize.create", "analytics"),
        input_schema=PROMPT_INPUT,
        output_schema=TEXT_OUTPUT,
        model_profile="default",
        guardrails=GUARDRAILS,
    )

    def run(self, value: Any, context: AgentContext) -> str:
        prompt = prompt_of(value)
        found = ids(DATASET_ID, prompt, 1)
        if not found:
            raise RuntimeError("Visualize requires a persisted dataset ID")
        dataset_id = found[0]
        description = context.warehouse.describe_dataset(dataset_id)
        columns = description.get("columns", [])
        numeric = [c["name"] for c in columns if is_numeric(c)]
        if not numeric:
            raise RuntimeError("Dataset has no numeric column to chart")
        spec = choose(context, prompt, [c["name"] for c in columns], numeric) or heuristic(columns, numeric)
        chart = context.tools.call(
            "warehouse.create_chart",
            {"datasetId": dataset_id, **spec, "title": spec["title"][:200] or description.get("name", "Chart")},
        )
        return f"Created {spec['kind']} chart {chart['id']} of {spec['y']} by {spec['x']} from {dataset_id}: {spec['title']}"


def choose(context: AgentContext, prompt: str, names: list[str], numeric: list[str]) -> dict | None:
    schema = {
        "type": "object",
        "properties": {
            "kind": {"enum": ["bar", "line"]},
            "x": {"enum": names},
            "y": {"enum": numeric},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "required": ["kind", "x", "y", "title"],
        "additionalProperties": False,
    }
    findings = f"Compare: {section(prompt, 'compare')}\nInsight: {section(prompt, 'insight')}"
    try:
        spec = ask_json(context, SYSTEM, f"{findings}\nColumns: {', '.join(names)}", schema)
    except RuntimeError:
        return None
    return spec if isinstance(spec, dict) and spec.get("x") != spec.get("y") else None


def heuristic(columns: list[dict], numeric: list[str]) -> dict:
    names = [c["name"] for c in columns]
    x = next((n for n in names if re.search(r"month|date|region|category|segment", n, re.I)), None)
    x = x or next((c["name"] for c in columns if not is_numeric(c)), names[0])
    y = next(n for n in numeric if n != x)
    kind = "line" if re.search(r"month|date", x, re.I) else "bar"
    return {"kind": kind, "x": x, "y": y, "title": f"{y} by {x}"}


if __name__ == "__main__":
    serve(VisualizeAgent())
