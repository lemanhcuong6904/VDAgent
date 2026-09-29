"""Insight specialist: explains trends that the supplied datasets actually support."""

from __future__ import annotations

from typing import Any

from _common import DATASET_ID, GUARDRAILS, PROMPT_INPUT, TEXT_OUTPUT, ask, ids, load_datasets, prompt_of
from agent_platform import AgentContext, AgentManifest, serve

SYSTEM = (
    "You are the Insight specialist. Explain trends and anomalies only when the supplied datasets "
    "support them. Separate evidence from hypotheses; label every unverified cause as a hypothesis. "
    "Cite dataset IDs and avoid recommendations unless requested. Keep it under 120 words."
)


class InsightAgent:
    manifest = AgentManifest(
        id="insight",
        version="1.0.0",
        name="Insight",
        description="Explains trends and anomalies using evidence from datasets.",
        tools=("warehouse.describe_dataset", "warehouse.get_dataset_rows"),
        capabilities=("dataset.insight", "analytics"),
        input_schema=PROMPT_INPUT,
        output_schema=TEXT_OUTPUT,
        model_profile="default",
        guardrails=GUARDRAILS,
    )

    def run(self, value: Any, context: AgentContext) -> str:
        prompt = prompt_of(value)
        datasets = load_datasets(context, ids(DATASET_ID, prompt))
        if not datasets:
            return "No persisted dataset ID was supplied, so no insight can be grounded."
        try:
            return ask(context, SYSTEM, prompt, datasets)
        except RuntimeError:
            # Model unavailable: report computed ranges only, never an inferred cause.
            lines = [
                f"{d['dataset_id']} {column}: range {s['min']}..{s['max']}, first-to-last change {s['change_pct']:+}%"
                for d in datasets
                for column, s in d.get("stats", {}).items()
            ]
            return "\n".join(lines) or "The supplied datasets have no numeric columns to explain."


if __name__ == "__main__":
    serve(InsightAgent())
