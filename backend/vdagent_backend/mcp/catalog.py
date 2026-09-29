"""The MCP tool catalog: names, descriptions and input schemas shown to models, and result fields.

Pure data. `RESULT_FIELDS` documents the top-level fields of each tool's successful JSON result; it
is rendered into the MCP tools reference (`vdagent_backend.mcp.reference`) and a test keeps it equal
to what the handlers return.
"""

from __future__ import annotations

from typing import Any

import mcp_types as types

from vdagent_backend.artifacts import CHART_KINDS
from vdagent_backend.warehouse import MAX_ROWS

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
