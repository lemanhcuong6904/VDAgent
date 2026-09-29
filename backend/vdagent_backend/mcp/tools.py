"""MCP tool catalog, per-agent permission matrix and handlers (§6.1).

Handlers return a JSON-able payload (sent as text content) or raise a user-facing error that
becomes an MCP tool error result `error: …`. Blocking sqlite3 work runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import mcp_types as types
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.db import artifact_store, artifacts, scopes
from vdagent_backend.mcp import re_sql, sql
from vdagent_backend.mcp.charts import CHART_KINDS, ChartError, build_chart_spec
from vdagent_backend.tokens import McpIdentity
from vdagent_contracts.envelope import ArtifactDraft, ArtifactEnvelope

PREVIEW_ROWS = 20
DEFAULT_PAGE_ROWS = 50
MAX_PAGE_ROWS = 200
_EMBED = re.compile(r"\{\{\s*(chart|dataset)\s*:\s*([^}\s]+)\s*\}\}")

ALL_AGENTS = frozenset({"orchestrator", "data", "compare", "insight", "report"})

# §6.1 permission matrix: tool → agents that see it in tools/list and may call it.
PERMISSIONS: dict[str, frozenset[str]] = {
    "list_tables": frozenset({"data"}),
    "describe_table": frozenset({"data"}),
    "run_query": frozenset({"data"}),
    "describe_dataset": ALL_AGENTS,
    "get_dataset_rows": ALL_AGENTS,
    "query_datasets": frozenset({"data", "compare", "insight"}),
    "create_chart": frozenset({"report"}),
    "save_report": frozenset({"report"}),
    "artifact_put": ALL_AGENTS,
    "artifact_get": ALL_AGENTS,
    "artifact_list": ALL_AGENTS,
    "get_user_context": ALL_AGENTS,
    "re_list_tables": frozenset({"data"}),
    "re_describe_table": frozenset({"data"}),
    "re_run_query": frozenset({"data"}),
}

# Artifact types each agent may write with artifact_put (system prompt §6.3: only its own types).
WRITABLE_TYPES: dict[str, set[str]] = {
    "orchestrator": {"run_summary", "run_state"},
    "data": {"data_package", "metric", "dq", "dataset"},
    "compare": {"peer_definition", "comparison", "market_context"},
    "insight": {"insight"},
    "chart": {"chart_spec"},
    "report": {"report"},
}

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
            "Run one read-only SELECT on the real-estate DW; rows outside your user's scope are never visible."
            " Set count_hidden=true to also get hidden_rows, the number of rows your scope removed."
            + _DATASET_RESULT
        ),
        input_schema=_schema(
            {"sql": {"type": "string"}, "name": _DATASET_NAME, "count_hidden": {"type": "boolean"}},
            ["sql"],
        ),
    ),
]


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


def _sort_key(value: Any) -> tuple[int, Any]:
    """SQLite ordering across storage classes: numbers before text."""
    return (0, value) if isinstance(value, int | float) else (1, str(value))


def _column_stats(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for i, column in enumerate(dataset["columns"]):
        present = [row[i] for row in dataset["rows"] if row[i] is not None]
        stats.append(
            {
                "name": column["name"],
                "type": column["type"],
                "min": min(present, key=_sort_key) if present else None,
                "max": max(present, key=_sort_key) if present else None,
                "null_count": len(dataset["rows"]) - len(present),
            }
        )
    return stats


def _text_result(text: str, *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


def tool_error(message: str) -> types.CallToolResult:
    return _text_result(f"error: {message}", is_error=True)


Handler = Callable[[McpIdentity, dict[str, Any]], Awaitable[dict[str, Any]]]


class McpTools:
    def __init__(
        self, db: AsyncEngine, warehouse_db: str, *, sql_timeout_s: float, re_warehouse_db: str = ""
    ) -> None:
        self._db = db
        self._warehouse_db = warehouse_db
        self._re_warehouse_db = re_warehouse_db
        self._timeout_s = sql_timeout_s
        self._handlers: dict[str, Handler] = {
            "list_tables": self._list_tables,
            "describe_table": self._describe_table,
            "run_query": self._run_query,
            "describe_dataset": self._describe_dataset,
            "get_dataset_rows": self._get_dataset_rows,
            "query_datasets": self._query_datasets,
            "create_chart": self._create_chart,
            "save_report": self._save_report,
            "artifact_put": self._artifact_put,
            "artifact_get": self._artifact_get,
            "artifact_list": self._artifact_list,
            "get_user_context": self._get_user_context,
            "re_list_tables": self._re_list_tables,
            "re_describe_table": self._re_describe_table,
            "re_run_query": self._re_run_query,
        }

    def list_for(self, agent: str) -> list[types.Tool]:
        return [tool for tool in TOOLS if agent in PERMISSIONS[tool.name]]

    async def call(self, identity: McpIdentity, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return tool_error(f"unknown tool '{name}'")
        if identity.agent not in PERMISSIONS[name]:
            return tool_error(f"tool '{name}' is not available to the {identity.agent} agent")
        try:
            payload = await handler(identity, arguments)
        except (ToolError, sql.SqlError, ChartError) as exc:
            return tool_error(str(exc))
        return _text_result(json.dumps(payload, ensure_ascii=False))

    # -- helpers --------------------------------------------------------------------------------

    async def _dataset(self, identity: McpIdentity, dataset_id: str) -> dict[str, Any]:
        dataset = await artifacts.get_dataset(self._db, identity.user_id, dataset_id)
        if dataset is None:
            raise ToolError("dataset not found")
        return dataset

    async def _store_dataset(
        self, identity: McpIdentity, name: str | None, source_sql: str, result: sql.QueryResult
    ) -> dict[str, Any]:
        dataset_id = await artifacts.insert_dataset(
            self._db,
            user_id=identity.user_id,
            invocation_id=identity.invocation_id,
            name=name,
            source_sql=source_sql,
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
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
        tables = await asyncio.to_thread(sql.warehouse_tables, self._warehouse_db, timeout_s=self._timeout_s)
        return {"tables": tables}

    async def _describe_table(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        table = _required_str(args, "table")
        return await asyncio.to_thread(sql.warehouse_describe, self._warehouse_db, table, timeout_s=self._timeout_s)

    async def _run_query(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(args, "sql")
        name = _optional_str(args, "name")
        result = await asyncio.to_thread(sql.warehouse_query, self._warehouse_db, query, timeout_s=self._timeout_s)
        return await self._store_dataset(identity, name, query, result)

    async def _describe_dataset(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset = await self._dataset(identity, _required_str(args, "dataset_id"))
        columns = await asyncio.to_thread(_column_stats, dataset)
        return {
            "dataset_id": dataset["id"],
            "name": dataset["name"],
            "row_count": dataset["row_count"],
            "truncated": dataset["truncated"],
            "source_sql": dataset["source_sql"],
            "columns": columns,
        }

    async def _get_dataset_rows(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset_id = _required_str(args, "dataset_id")
        offset = _int(args, "offset", 0, 0)
        limit = _int(args, "limit", DEFAULT_PAGE_ROWS, 1, MAX_PAGE_ROWS)
        dataset = await self._dataset(identity, dataset_id)
        return {
            "dataset_id": dataset["id"],
            "columns": dataset["columns"],
            "row_count": dataset["row_count"],
            "offset": offset,
            "limit": limit,
            "rows": dataset["rows"][offset : offset + limit],
        }

    async def _query_datasets(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        query = _required_str(args, "sql")
        dataset_ids = list(dict.fromkeys(_str_list(args, "dataset_ids")))
        name = _optional_str(args, "name")
        sql.check_select(query)
        datasets: list[dict[str, Any]] = []
        for dataset_id in dataset_ids:
            dataset = await artifacts.get_dataset(self._db, identity.user_id, dataset_id)
            if dataset is None:
                raise ToolError(f"dataset not found: {dataset_id}")
            datasets.append(dataset)
        result = await asyncio.to_thread(sql.datasets_query, query, datasets, timeout_s=self._timeout_s)
        return await self._store_dataset(identity, name, query, result)

    async def _create_chart(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset_id = _required_str(args, "dataset_id")
        kind = _required_str(args, "kind")
        x = _required_str(args, "x")
        y = _str_list(args, "y")
        title = _required_str(args, "title")
        dataset = await self._dataset(identity, dataset_id)
        spec = await asyncio.to_thread(build_chart_spec, dataset, kind, x, y, title)
        chart_id = await artifacts.insert_chart(
            self._db,
            user_id=identity.user_id,
            invocation_id=identity.invocation_id,
            dataset_id=dataset_id,
            title=title,
            spec=spec,
        )
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
        refs: dict[str, set[str]] = {"charts": set(), "datasets": set()}
        for kind, artifact_id in _EMBED.findall(markdown):
            refs[f"{kind}s"].add(artifact_id)
        missing: set[str] = set()
        for table, ids in refs.items():
            missing |= ids - await artifacts.existing_artifact_ids(self._db, identity.user_id, table, ids)
        if missing:
            raise ToolError(f"markdown references unknown ids: {', '.join(sorted(missing))}")
        report_id = await artifacts.insert_report(
            self._db, user_id=identity.user_id, invocation_id=identity.invocation_id, title=title, markdown=markdown
        )
        return {"report_id": report_id, "title": title}

    async def _artifact_put(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        raw = _required_str(args, "draft_json")
        try:
            draft = ArtifactDraft.model_validate(json.loads(raw, parse_float=Decimal))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ToolError(f"invalid artifact draft: {exc}") from exc
        if draft.artifact_type.value not in WRITABLE_TYPES.get(identity.agent, set()):
            raise ToolError(f"the {identity.agent} agent cannot write {draft.artifact_type.value} artifacts")
        run_id = _optional_str(args, "run_id") or identity.task_id
        if run_id != identity.task_id and not await artifact_store.list_artifacts(
            self._db, identity.user_id, run_id=run_id
        ):
            raise ToolError(f"unknown run {run_id}: write to the current task or a run you already have")
        try:
            stored = await artifact_store.put(
                self._db, user_id=identity.user_id, run_id=run_id, task_id=identity.task_id, draft=draft
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return stored.model_dump(mode="json")

    async def _artifact_get(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        artifact_id = _required_str(args, "artifact_id")
        version = args.get("version")
        if version is not None and (not isinstance(version, int) or version < 1):
            raise ToolError("'version' must be a positive integer")
        envelope = await artifact_store.get(self._db, identity.user_id, artifact_id, version=version)
        if envelope is None:
            raise ToolError("artifact not found")
        return envelope.model_dump(mode="json")

    async def _artifact_list(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        envelopes = await artifact_store.list_artifacts(
            self._db,
            identity.user_id,
            run_id=_optional_str(args, "run_id"),
            artifact_type=_optional_str(args, "artifact_type"),
        )
        return {"artifacts": [_summary(e) for e in envelopes]}

    async def _get_user_context(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        if args:
            raise ToolError("get_user_context takes no arguments: the user comes from your credentials")
        context = await scopes.get_user_context(self._db, identity.user_id)
        return context.model_dump(mode="json")

    async def _re_scope(self, identity: McpIdentity) -> Any:
        if not self._re_warehouse_db:
            raise ToolError("the real-estate warehouse is not configured (re_warehouse_db)")
        return (await scopes.get_user_context(self._db, identity.user_id)).authorized_scope

    async def _re_list_tables(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        scope = await self._re_scope(identity)
        tables = await asyncio.to_thread(re_sql.scoped_tables, self._re_warehouse_db, scope, timeout_s=self._timeout_s)
        return {"tables": tables}

    async def _re_describe_table(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        scope = await self._re_scope(identity)
        table = _required_str(args, "table")
        sample_rows = _int(args, "sample_rows", 5, 0, 20)
        return await asyncio.to_thread(
            re_sql.scoped_describe, self._re_warehouse_db, table, scope, timeout_s=self._timeout_s, sample_rows=sample_rows
        )

    async def _re_run_query(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        scope = await self._re_scope(identity)
        query = _required_str(args, "sql")
        count_hidden = args.get("count_hidden", False)
        if not isinstance(count_hidden, bool):
            raise ToolError("'count_hidden' must be a boolean")
        result, hidden = await asyncio.to_thread(
            re_sql.scoped_query, self._re_warehouse_db, query, scope, timeout_s=self._timeout_s, count_hidden=count_hidden
        )
        payload = await self._store_dataset(identity, _optional_str(args, "name"), query, result)
        if hidden is not None:
            payload["hidden_rows"] = hidden
        return payload


def _summary(envelope: ArtifactEnvelope) -> dict[str, Any]:
    return envelope.model_dump(mode="json", exclude={"payload"})
