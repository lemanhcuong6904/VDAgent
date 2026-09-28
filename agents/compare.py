"""Compare specialist: quantifies changes across persisted datasets."""

from __future__ import annotations

from typing import Any

from _common import DATASET_ID, GUARDRAILS, PROMPT_INPUT, TEXT_OUTPUT, ask, ids, load_datasets, prompt_of
from agent_platform import AgentContext, AgentManifest, serve

SYSTEM = (
    "You are the Compare specialist. Compare only the supplied datasets. Quantify absolute and "
    "percentage changes using the precomputed stats. State the compared periods and dataset IDs. "
    "Do not invent missing data or paste raw rows. Keep it under 120 words."
)


class CompareAgent:
    manifest = AgentManifest(
        id="compare",
        version="1.0.0",
        name="Compare",
        description="Compares periods and segments from supplied warehouse datasets.",
        tools=("warehouse.describe_dataset", "warehouse.get_dataset_rows"),
        capabilities=("dataset.compare", "analytics"),
        input_schema=PROMPT_INPUT,
        output_schema=TEXT_OUTPUT,
        model_profile="default",
        guardrails=GUARDRAILS,
    )

    def run(self, value: Any, context: AgentContext) -> str:
        prompt = prompt_of(value)
        datasets = load_datasets(context, ids(DATASET_ID, prompt))
        if not datasets:
            return "No persisted dataset ID was supplied, so nothing was compared."
        try:
            return ask(context, SYSTEM, prompt, datasets)
        except RuntimeError:
            lines = [
                f"{d['dataset_id']} {column}: {s['first']} -> {s['last']} ({s['change_pct']:+}%)"
                for d in datasets
                for column, s in d.get("stats", {}).items()
            ]
            return "\n".join(lines) or "The supplied datasets have no numeric columns to compare."


if __name__ == "__main__":
    serve(CompareAgent())
