"""Data specialist: finds warehouse tables and persists a dataset other agents can cite."""

from __future__ import annotations

from typing import Any

from _common import DATASET_ID, GUARDRAILS, PROMPT_INPUT, TEXT_OUTPUT, ask, ask_json, ids, prompt_of
from agent_platform import AgentContext, AgentManifest, serve

SYSTEM = (
    "You are the Data specialist. Summarize only the verified warehouse evidence: dataset ID, "
    "grain, columns, filters, row count and concise caveats. A table name is never a dataset ID. "
    "Do not interpret trends, recommend actions or paste raw rows."
)


class DataAgent:
    manifest = AgentManifest(
        id="data",
        version="1.0.0",
        name="Data",
        description="Finds warehouse data and returns datasets with clear column definitions.",
        tools=(
            "warehouse.list_sources",
            "warehouse.list_tables",
            "warehouse.describe_table",
            "warehouse.run_query",
            "warehouse.describe_dataset",
            "warehouse.get_dataset_rows",
        ),
        capabilities=("warehouse.discovery", "warehouse.query", "dataset.create", "data.prepare", "analytics"),
        input_schema=PROMPT_INPUT,
        output_schema=TEXT_OUTPUT,
        model_profile="default",
        guardrails=GUARDRAILS,
    )

    def run(self, value: Any, context: AgentContext) -> str:
        prompt = prompt_of(value)
        try:
            evidence = self.prepare(context, prompt)
        except RuntimeError as error:
            evidence = {"preflight_error": str(error)}
        dataset_id = (evidence.get("dataset") or {}).get("dataset_id")
        try:
            summary = ask(context, SYSTEM, prompt, evidence)
        except RuntimeError:
            summary = fallback(evidence)
        if not dataset_id:
            return summary
        return summary if dataset_id in summary else f"{summary}\n\nPersisted dataset: {dataset_id}"

    def prepare(self, context: AgentContext, prompt: str) -> dict:
        existing = ids(DATASET_ID, prompt, 1)
        if existing:
            return {"dataset": {"dataset_id": existing[0], **context.warehouse.describe_dataset(existing[0])}}
        sources = context.warehouse.list_sources().get("warehouses", [])
        if not sources:
            return {"error": "No warehouse provider is registered"}
        lowered = prompt.lower()
        warehouse = next((s for s in sources if s["id"].lower() in lowered), sources[0])
        tables = context.warehouse.list_tables(warehouse["id"]).get("tables", [])
        table = next((t["name"] for t in tables if t["name"].lower() in lowered), None)
        if table is None and tables:
            table = pick_table(context, prompt, [t["name"] for t in tables])
        if table is None:
            return {"warehouse": warehouse, "tables": tables, "note": "No table matches the request"}
        description = context.warehouse.describe_table({"warehouseId": warehouse["id"], "table": table})
        dataset = context.warehouse.run_query({"warehouseId": warehouse["id"], "table": table, "limit": 100})
        if not isinstance(dataset, dict) or not dataset.get("dataset_id"):
            raise RuntimeError("Warehouse query did not return a persisted dataset ID")
        return {"warehouse": warehouse, "table": description, "dataset": dataset}


def pick_table(context: AgentContext, prompt: str, names: list[str]) -> str | None:
    """Let the model choose among real table names only; the schema enum forbids inventions."""
    schema = {
        "type": "object",
        "properties": {"table": {"enum": [*names, None]}},
        "required": ["table"],
        "additionalProperties": False,
    }
    try:
        choice = ask_json(
            context,
            "Pick the warehouse table that answers the request, or null when none fits.",
            f"Request: {prompt}\nTables: {', '.join(names)}",
            schema,
        )
    except RuntimeError:
        return None
    return choice.get("table") if isinstance(choice, dict) else None


def fallback(evidence: dict) -> str:
    dataset = evidence.get("dataset")
    if not dataset:
        return f"No persisted dataset was created. Evidence: {evidence}"
    columns = ", ".join(c["name"] for c in dataset.get("columns", []))
    return f"Dataset {dataset['dataset_id']} ({dataset.get('name')}): {dataset.get('row_count')} rows; columns {columns}."


if __name__ == "__main__":
    serve(DataAgent())
