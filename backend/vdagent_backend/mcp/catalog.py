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
            "Save a markdown report and return its report_id. Embed charts with {{chart:<chart_id>}},"
            " chart_spec artifacts with {{chart_spec:<artifact_id>@<version>}} and dataset tables with"
            " {{dataset:<dataset_id>}} on their own lines."
        ),
        input_schema=_schema(
            {"title": {"type": "string"}, "markdown": {"type": "string"}},
            ["title", "markdown"],
        ),
    ),
    types.Tool(
        name="artifact_put",
        description=(
            "Store an immutable artifact envelope draft (JSON string: artifact_type, schema_version, status,"
            " producer, payload, ...; decimal numbers are kept exact). Set artifact_id in the draft to store"
            " a new version of that artifact. Returns the stored envelope."
        ),
        input_schema=_schema(
            {
                "draft_json": {"type": "string", "description": "ArtifactDraft as a JSON string."},
                "run_id": {"type": "string", "description": "Run to file it under; default: the current task."},
            },
            ["draft_json"],
        ),
    ),
    types.Tool(
        name="artifact_get",
        description="Read one artifact envelope with its payload (latest version unless version is given).",
        input_schema=_schema(
            {
                "artifact_id": {"type": "string", "description": "Artifact id (art_...)."},
                "version": {"type": "integer", "minimum": 1},
            },
            ["artifact_id"],
        ),
    ),
    types.Tool(
        name="artifact_list",
        description="List your artifacts (latest versions, without payloads), optionally by run and type.",
        input_schema=_schema({"run_id": {"type": "string"}, "artifact_type": {"type": "string"}}, []),
    ),
    types.Tool(
        name="get_user_context",
        description=(
            "Your user's context: user_id, role and authorized_scope (project_ids, zone_ids). Pass it verbatim;"
            " never take scope from the question."
        ),
        input_schema=_schema({}, []),
    ),
    types.Tool(
        name="re_list_tables",
        description="List the real-estate DW tables (DW v3.1.0 mock) with the row counts you are allowed to see.",
        input_schema=_schema({}, []),
    ),
    types.Tool(
        name="re_describe_table",
        description="Columns and sample rows (within your scope) of one real-estate DW table.",
        input_schema=_schema(
            {"table": {"type": "string"}, "sample_rows": {"type": "integer", "minimum": 0, "maximum": 20}},
            ["table"],
        ),
    ),
    types.Tool(
        name="re_run_query",
        description=(
            "Run one read-only SELECT on the real-estate DW; rows outside your user's scope are never visible,"
            " not even as a count." + _DATASET_RESULT
        ),
        input_schema=_schema({"sql": {"type": "string"}, "name": _DATASET_NAME}, ["sql"]),
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

_ENVELOPE_FIELDS: dict[str, str] = {
    "artifact_id": "Artifact id (`art_…`).",
    "run_id": "The run (task) the artifact is filed under.",
    "task_id": "The task whose invocation wrote this version.",
    "user_id": "The owning user.",
    "artifact_type": "e.g. dataset, insight, comparison, chart_spec, report, run_state.",
    "schema_version": "The payload schema, e.g. `re_dataset@1`.",
    "version": "1 for a new artifact; each new version supersedes the previous ones.",
    "status": "DRAFT, VALID, PARTIAL, INVALID or SUPERSEDED.",
    "producer": "`{agent, agent_version, prompt_version, model_id}`.",
    "content_hash": "sha256 of the canonical content, computed by the store.",
    "snapshot_refs": "The data snapshot(s) the content is pinned to.",
    "semantic_config_version": "The semantic config version, or null.",
    "source_refs": "Source references of the content.",
    "input_artifact_refs": "`[{artifact_id, version, artifact_type, content_hash}]` the content was built from.",
    "evidence_refs": "Evidence artifact refs.",
    "limitations": "Limitation codes (a PARTIAL artifact has at least one).",
    "reason_code": "Why the status is not VALID, or null.",
    "reason": "Human-readable reason, or null.",
    "payload": "The producer's content (decimals as strings).",
    "created_at": "When this version was stored.",
}

RESULT_FIELDS.update({
    "artifact_put": _ENVELOPE_FIELDS,
    "artifact_get": _ENVELOPE_FIELDS,
    "artifact_list": {"artifacts": "Latest version of each artifact: every envelope field except `payload`."},
    "get_user_context": {
        "user_id": "Your user.",
        "role": "The user's role, or null.",
        "authorized_scope": "`{project_ids, zone_ids}` the user may see; never widen it.",
    },
    "re_list_tables": {"tables": "`[{name, row_count}]`; the counts include only rows inside your scope."},
    "re_describe_table": {
        "table": "The table name.",
        "columns": "`[{name, type}]`.",
        "sample_rows": "Up to `sample_rows` rows inside your scope.",
    },
    "re_run_query": {
        **_DATASET_FIELDS,
        "warehouse": "Which DW answered, without credentials: `{backend: postgresql, host, port, database}` for the real"
        " warehouse or `{backend: sqlite, file}` for the synthetic mock. Label your data from it.",
    },
})
