"""MCP tool catalog and handlers.

Which agent may call which tool is not decided here: grants come from each plugin entry's
`mcp_tools` (see `AgentRegistry.tools_for`).

Handlers return a JSON-able payload (sent as text content) or raise a user-facing error that
becomes an MCP tool error result `error: …`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import mcp_types as types

from vdagent_backend.artifacts import CHART_KINDS, ArtifactError, ArtifactService
from vdagent_backend.core import McpIdentity
from vdagent_backend.warehouse import MAX_ROWS, QueryResult, SqlError, Warehouse, check_select

PREVIEW_ROWS = 20
DEFAULT_PAGE_ROWS = 50
MAX_PAGE_ROWS = 200

_DATASET_RESULT = (
    ' Returns {"dataset_id", "name", "columns": [{"name", "type"}], "row_count", "truncated", "preview"}'
    " where preview holds the first 20 rows; results are capped at 10 000 rows (truncated=true)."
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_DATASET_ID = {"type": "string", "description": "Dataset id (ds_…)."}
_DATASET_NAME = {"type": "string", "description": "Optional short name for the new dataset."}

TOOLS: list[types.Tool] = [
    types.Tool(
        name="list_tables",
        description="List the warehouse tables with their row counts.",
        input_schema=_schema({}, []),
    ),
    types.Tool(
        name="describe_table",
        description="Describe a warehouse table: its columns with types and 5 sample rows.",
        input_schema=_schema({"table": {"type": "string", "description": "Warehouse table name."}}, ["table"]),
    ),
    types.Tool(
        name="run_query",
        description=(
            "Run one read-only SQLite SELECT (or WITH … SELECT) statement on the warehouse and store the"
            " result as a new dataset. Queries are limited to 10 seconds." + _DATASET_RESULT
        ),
        input_schema=_schema(
            {"sql": {"type": "string", "description": "A single SELECT / WITH … SELECT statement."}, "name": _DATASET_NAME},
            ["sql"],
        ),
    ),
    types.Tool(
        name="describe_dataset",
        description="Describe a dataset: columns, row count, and per-column min / max / null count.",
        input_schema=_schema({"dataset_id": _DATASET_ID}, ["dataset_id"]),
    ),
    types.Tool(
        name="get_dataset_rows",
        description=f"Read a page of a dataset's rows (at most {MAX_PAGE_ROWS} per call).",
        input_schema=_schema(
            {
                "dataset_id": _DATASET_ID,
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_ROWS, "default": DEFAULT_PAGE_ROWS},
            },
            ["dataset_id"],
        ),
    ),
    types.Tool(
        name="query_datasets",
        description=(
            "Run one SQLite SELECT (or WITH … SELECT) over existing datasets and store the result as a new"
            " dataset. Each listed dataset is a table named by its id, e.g."
            ' SELECT a.region, b.revenue - a.revenue AS delta FROM "ds_…" a JOIN "ds_…" b USING (region).'
            + _DATASET_RESULT
        ),
        input_schema=_schema(
            {
                "sql": {"type": "string", "description": "A single SELECT / WITH … SELECT statement."},
                "dataset_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Datasets the query reads; each is loaded as a table named by its id.",
                },
                "name": _DATASET_NAME,
            },
            ["sql", "dataset_ids"],
        ),
    ),
    types.Tool(
        name="create_chart",
        description=(
            "Build a Vega-Lite chart from a dataset. bar/line: x is the category or date column, each y"
            " column becomes a series; pie: x gives the slices and y[0] their size."
            ' Returns {"chart_id", "embed"}; put the embed text ({{chart:<id>}}) into a report.'
        ),
        input_schema=_schema(
            {
                "dataset_id": _DATASET_ID,
                "kind": {"type": "string", "enum": list(CHART_KINDS)},
                "x": {"type": "string", "description": "Column for the x axis (or pie slices)."},
                "y": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Numeric column(s) to plot.",
                },
                "title": {"type": "string"},
            },
            ["dataset_id", "kind", "x", "y", "title"],
        ),
    ),
    types.Tool(
        name="save_report",
        description=(
            "Save a markdown report and return its report_id. Embed charts with {{chart:<chart_id>}} and"
            " dataset tables with {{dataset:<dataset_id>}} on their own lines."
        ),
        input_schema=_schema(
            {"title": {"type": "string"}, "markdown": {"type": "string"}},
            ["title", "markdown"],
        ),
    ),
]

TOOL_NAMES = frozenset(tool.name for tool in TOOLS)

_DATASET_FIELDS: dict[str, str] = {
    "dataset_id": "Id of the new dataset (`ds_…`); pass it to other tools or to another agent.",
    "name": "The `name` argument, or null.",
    "columns": "`[{name, type}]`; type is INTEGER, REAL or TEXT (TEXT when every value is null).",
    "row_count": f"Rows stored, at most {MAX_ROWS:,}.",
    "truncated": f"true when the query returned more than {MAX_ROWS:,} rows and the rest were dropped.",
    "preview": f"The first {PREVIEW_ROWS} rows, each a list of values in column order.",
}

# Top-level fields of each tool's successful JSON result, with their meaning. Rendered into the MCP
# tools reference (`vdagent_backend.mcp.reference`); a test keeps it equal to what the handlers return.
RESULT_FIELDS: dict[str, dict[str, str]] = {
    "list_tables": {"tables": "`[{name, row_count}]`, one entry per warehouse table."},
    "describe_table": {
        "table": "The table name.",
        "columns": "`[{name, type}]` as declared in the warehouse.",
        "sample_rows": "Up to 5 rows, each a list of values in column order.",
    },
    "run_query": _DATASET_FIELDS,
    "describe_dataset": {
        "dataset_id": "The dataset id.",
        "name": "The dataset's name, or null.",
        "row_count": "Rows stored.",
        "truncated": "true when the dataset was cut at the row cap.",
        "source_sql": "The SQL that produced the dataset.",
        "columns": "`[{name, type, min, max, null_count}]`; min/max are null when every value is null.",
    },
    "get_dataset_rows": {
        "dataset_id": "The dataset id.",
        "columns": "`[{name, type}]`.",
        "row_count": "Total rows in the dataset; page until `offset + limit >= row_count`.",
        "offset": "The offset used.",
        "limit": "The limit used.",
        "rows": "The page, each row a list of values in column order.",
    },
    "query_datasets": _DATASET_FIELDS,
    "create_chart": {
        "chart_id": "Id of the new chart (`ch_…`).",
        "title": "The chart title.",
        "dataset_id": "The charted dataset.",
        "kind": "bar, line or pie.",
        "embed": "`{{chart:<chart_id>}}`; put it on its own line in a `save_report` markdown.",
    },
    "save_report": {
        "report_id": "Id of the saved report (`rp_…`).",
        "title": "The report title.",
    },
}


class ToolError(Exception):
    """A user-facing tool failure; its message becomes the tool error text."""


def _required_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' is required and must be a non-empty string")
    return value.strip()


def _optional_str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"'{key}' must be a string")
    return value.strip() or None


def _int(args: dict[str, Any], key: str, default: int, low: int, high: int | None = None) -> int:
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"'{key}' must be an integer")
    if value < low or (high is not None and value > high):
        bounds = f"between {low} and {high}" if high is not None else f">= {low}"
        raise ToolError(f"'{key}' must be {bounds}")
    return value


def _str_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise ToolError(f"'{key}' must be a non-empty array of strings")
    return [v.strip() for v in value]


def _text_result(text: str, *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


def tool_error(message: str) -> types.CallToolResult:
    return _text_result(f"error: {message}", is_error=True)


Handler = Callable[[McpIdentity, dict[str, Any]], Awaitable[dict[str, Any]]]


class McpTools:
    def __init__(self, artifacts: ArtifactService, warehouse: Warehouse) -> None:
        self._artifacts = artifacts
        self._warehouse = warehouse
        self._handlers: dict[str, Handler] = {
            "list_tables": self._list_tables,
            "describe_table": self._describe_table,
            "run_query": self._run_query,
            "describe_dataset": self._describe_dataset,
            "get_dataset_rows": self._get_dataset_rows,
            "query_datasets": self._query_datasets,
            "create_chart": self._create_chart,
            "save_report": self._save_report,
        }

    async def call(
        self, identity: McpIdentity, granted: frozenset[str], name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """Run tool `name` for `identity`, whose agent may call the `granted` tools."""
        handler = self._handlers.get(name)
        if handler is None:
            return tool_error(f"unknown tool '{name}'")
        if name not in granted:
            return tool_error(f"tool '{name}' is not available to the {identity.agent} agent")
        try:
            payload = await handler(identity, arguments)
        except (ToolError, SqlError, ArtifactError) as exc:
            return tool_error(str(exc))
        return _text_result(json.dumps(payload, ensure_ascii=False))

    # -- helpers --------------------------------------------------------------------------------

    async def _store_dataset(
        self, identity: McpIdentity, name: str | None, source_sql: str, result: QueryResult
    ) -> dict[str, Any]:
        dataset_id = await self._artifacts.store_dataset(
            identity.user_id, identity.invocation_id, name, source_sql, result
        )
        return {
            "dataset_id": dataset_id,
            "name": name,
            "columns": result.columns,
            "row_count": len(result.rows),
            "truncated": result.truncated,
            "preview": result.rows[:PREVIEW_ROWS],
        }

    # -- tools ----------------------------------------------------------------------------------

    async def _list_tables(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        return {"tables": await self._warehouse.tables()}

    async def _describe_table(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        return await self._warehouse.describe(_required_str(args, "table"))

    async def _run_query(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(args, "sql")
        name = _optional_str(args, "name")
        return await self._store_dataset(identity, name, query, await self._warehouse.query(query))

    async def _describe_dataset(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        described = await self._artifacts.describe_dataset(identity.user_id, _required_str(args, "dataset_id"))
        if described is None:
            raise ToolError("dataset not found")
        return described

    async def _get_dataset_rows(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset_id = _required_str(args, "dataset_id")
        offset = _int(args, "offset", 0, 0)
        limit = _int(args, "limit", DEFAULT_PAGE_ROWS, 1, MAX_PAGE_ROWS)
        page = await self._artifacts.dataset_page(identity.user_id, dataset_id, offset, limit)
        if page is None:
            raise ToolError("dataset not found")
        return {
            "dataset_id": page["id"],
            "columns": page["columns"],
            "row_count": page["row_count"],
            "offset": offset,
            "limit": limit,
            "rows": page["rows"],
        }

    async def _query_datasets(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(args, "sql")
        dataset_ids = list(dict.fromkeys(_str_list(args, "dataset_ids")))
        name = _optional_str(args, "name")
        check_select(query)
        datasets = await self._artifacts.datasets(identity.user_id, dataset_ids)
        return await self._store_dataset(identity, name, query, await self._warehouse.query_datasets(query, datasets))

    async def _create_chart(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset_id = _required_str(args, "dataset_id")
        kind = _required_str(args, "kind")
        x = _required_str(args, "x")
        y = _str_list(args, "y")
        title = _required_str(args, "title")
        chart_id = await self._artifacts.create_chart(
            identity.user_id, identity.invocation_id, dataset_id, kind, x, y, title
        )
        if chart_id is None:
            raise ToolError("dataset not found")
        return {
            "chart_id": chart_id,
            "title": title,
            "dataset_id": dataset_id,
            "kind": kind,
            "embed": f"{{{{chart:{chart_id}}}}}",
        }

    async def _save_report(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        title = _required_str(args, "title")
        markdown = _required_str(args, "markdown")
        report_id = await self._artifacts.save_report(identity.user_id, identity.invocation_id, title, markdown)
        return {"report_id": report_id, "title": title}
