"""External agent whose pipeline is built with LangChain (langchain-core).

LangChain only orchestrates here: every data access is a granted host tool reached through
`context.tools`, so ToolPool policy and the evidence ledger still apply. The runner strips
credentials from the child environment, so this agent never calls a model provider directly.
"""
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool

from agent_platform import AgentContext, AgentManifest, serve

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "table": {"type": "string", "minLength": 1, "maxLength": 128},
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
    },
    "additionalProperties": False,
}


def granted_tools(context: AgentContext) -> dict[str, StructuredTool]:
    """Expose host tools as LangChain tools; the host still enforces the manifest grants."""

    def list_tables() -> Any:
        return context.tools.call("warehouse.list_tables", {})

    def run_query(table: str, limit: int = 100) -> Any:
        return context.tools.call("warehouse.run_query", {"table": table, "limit": limit})

    return {
        "list_tables": StructuredTool.from_function(
            list_tables, name="list_tables", description="List warehouse tables."
        ),
        "run_query": StructuredTool.from_function(
            run_query, name="run_query", description="Read rows from one table."
        ),
    }


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    result = state["result"]
    # run_query returns `rows` without artifact storage and `preview` when the dataset is persisted.
    rows = result.get("rows") or result.get("preview") or []
    numeric: dict[str, dict[str, float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                stats = numeric.setdefault(key, {"sum": 0.0, "min": value, "max": value})
                stats["sum"] += value
                stats["min"] = min(stats["min"], value)
                stats["max"] = max(stats["max"], value)
    return {
        "table": state["table"],
        "rowCount": result.get("row_count", len(rows)),
        "datasetId": result.get("dataset_id"),
        "numericColumns": numeric,
    }


def build_pipeline(context: AgentContext):
    tools = granted_tools(context)

    def pick_table(value: dict[str, Any]) -> dict[str, Any]:
        table = value.get("table")
        if not table:
            tables = tools["list_tables"].invoke({}).get("tables", [])
            if not tables:
                raise RuntimeError("Warehouse has no tables")
            table = tables[0]["name"]
        return {"table": table, "limit": value.get("limit", 100)}

    def query(state: dict[str, Any]) -> dict[str, Any]:
        result = tools["run_query"].invoke({"table": state["table"], "limit": state["limit"]})
        return {**state, "result": result}

    return RunnableLambda(pick_table) | RunnableLambda(query) | RunnableLambda(summarize)


class LangChainAnalyticsAgent:
    manifest = AgentManifest(
        id="example.python.langchain",
        version="1.0.0",
        name="LangChain analytics example",
        description="Summarizes numeric columns of a warehouse table with a LangChain pipeline.",
        capabilities=("example.langchain.summary",),
        tools=("warehouse.list_tables", "warehouse.run_query"),
        input_schema=INPUT_SCHEMA,
    )

    def run(self, value: dict, context: AgentContext) -> dict:
        return build_pipeline(context).invoke(value or {})


if __name__ == "__main__":
    serve(LangChainAnalyticsAgent())
