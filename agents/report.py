"""Report specialist: drafts findings with the model and saves a Markdown report artifact."""

from __future__ import annotations

from typing import Any

from _common import (
    CHART_ID,
    DATASET_ID,
    GUARDRAILS,
    PROMPT_INPUT,
    TEXT_OUTPUT,
    ask,
    ids,
    load_datasets,
    prompt_of,
    section,
)
from agent_platform import AgentContext, AgentManifest, serve

SYSTEM = (
    "You are the Report specialist. Write a concise executive summary (under 150 words) from the "
    "supplied Compare, Insight and Visualize findings and dataset stats. Do not add unsupported "
    "causes, invent values or artifact IDs, or paste bulk rows. Return Markdown without headings."
)


class ReportAgent:
    manifest = AgentManifest(
        id="report",
        version="1.0.0",
        name="Report",
        description="Writes and saves reports from comparison, insight, and visualization findings.",
        tools=("warehouse.describe_dataset", "warehouse.get_dataset_rows", "warehouse.save_report"),
        capabilities=("dataset.report", "report.generate", "analytics"),
        input_schema=PROMPT_INPUT,
        output_schema=TEXT_OUTPUT,
        model_profile="default",
        guardrails=GUARDRAILS,
    )

    def run(self, value: Any, context: AgentContext) -> str:
        prompt = prompt_of(value)
        found = ids(DATASET_ID, prompt, 1)
        if not found:
            raise RuntimeError("Report requires a persisted dataset ID")
        dataset = load_datasets(context, found, rows=20)[0]
        if "error" in dataset:
            raise RuntimeError(f"Dataset {found[0]} is unavailable")
        chart_id = next(iter(ids(CHART_ID, prompt, 1)), None)
        findings = {agent: section(prompt, agent) for agent in ("compare", "insight", "visualize")}
        try:
            draft = ask(context, SYSTEM, prompt, {"findings": findings, "dataset": dataset})
        except RuntimeError:
            draft = ""  # The saved report still carries the specialist findings verbatim.
        title = f"{dataset.get('name') or found[0]} analysis"
        report = context.tools.call(
            "warehouse.save_report", {"title": title[:200], "markdown": markdown(title, dataset, chart_id, findings, draft)}
        )
        chart = f" with chart {chart_id}" if chart_id else ""
        return f"Report {report['id']} saved{chart} from dataset {found[0]}."


def markdown(title: str, dataset: dict, chart_id: str | None, findings: dict, draft: str) -> str:
    names = [c["name"] for c in dataset.get("columns", [])]
    cell = lambda value: str("" if value is None else value).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    table = [f"| {' | '.join(names)} |", f"| {' | '.join('---' for _ in names)} |"]
    table += [f"| {' | '.join(cell(row.get(n)) for n in names)} |" for row in dataset.get("preview", [])[:10]]
    parts = [f"# {title}", "", f"Source dataset: {{{{dataset:{dataset['dataset_id']}}}}}", ""]
    if draft:
        parts += ["## Summary", "", draft[:10_000], ""]
    parts += ["## Comparison", "", findings["compare"], "", "## Insight", "", findings["insight"], ""]
    parts += ["## Visualization", "", findings["visualize"], ""]
    if chart_id:
        parts += [f"{{{{chart:{chart_id}}}}}", ""]
    parts += ["## Data preview", "", *table, ""]
    parts.append("The report summarizes the supplied specialist findings and persisted dataset. No causal explanation is asserted.")
    return "\n".join(parts)[:20_000]


if __name__ == "__main__":
    serve(ReportAgent())
