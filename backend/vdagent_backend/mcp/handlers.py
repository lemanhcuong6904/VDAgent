"""MCP tool handlers: one method per tool, on `ArtifactService` and `Warehouse`.

A handler returns a JSON-able payload (sent as text content) or raises a user-facing error
(`ToolError`, `SqlError`, `ArtifactError`) that becomes the tool error result `error: <text>`.
Grants are checked before a handler runs.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import mcp_types as types

from vdagent_backend.artifacts import ArtifactError, ArtifactService
from vdagent_backend.core import McpIdentity
from vdagent_backend.mcp.args import ToolError, bounded_int, optional_str, required_str, str_list
from vdagent_backend.mcp.catalog import DEFAULT_PAGE_ROWS, MAX_PAGE_ROWS, PREVIEW_ROWS
from vdagent_backend.warehouse import QueryResult, SqlError, Warehouse, check_select

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
        return await self._warehouse.describe(required_str(args, "table"))

    async def _run_query(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        query = required_str(args, "sql")
        name = optional_str(args, "name")
        return await self._store_dataset(identity, name, query, await self._warehouse.query(query))

    async def _describe_dataset(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        described = await self._artifacts.describe_dataset(identity.user_id, required_str(args, "dataset_id"))
        if described is None:
            raise ToolError("dataset not found")
        return described

    async def _get_dataset_rows(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset_id = required_str(args, "dataset_id")
        offset = bounded_int(args, "offset", 0, 0)
        limit = bounded_int(args, "limit", DEFAULT_PAGE_ROWS, 1, MAX_PAGE_ROWS)
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
        query = required_str(args, "sql")
        dataset_ids = list(dict.fromkeys(str_list(args, "dataset_ids")))
        name = optional_str(args, "name")
        check_select(query)
        datasets = await self._artifacts.datasets(identity.user_id, dataset_ids)
        return await self._store_dataset(identity, name, query, await self._warehouse.query_datasets(query, datasets))

    async def _create_chart(self, identity: McpIdentity, args: dict[str, Any]) -> dict[str, Any]:
        dataset_id = required_str(args, "dataset_id")
        kind = required_str(args, "kind")
        x = required_str(args, "x")
        y = str_list(args, "y")
        title = required_str(args, "title")
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
        title = required_str(args, "title")
        markdown = required_str(args, "markdown")
        report_id = await self._artifacts.save_report(identity.user_id, identity.invocation_id, title, markdown)
        return {"report_id": report_id, "title": title}
