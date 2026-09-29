"""Test doubles for the Data agent: an MCP session over the real DW mock with the Backend's scoped SQL (test-only
import of vdagent_backend, DEC-032) and an in-memory Artifact Store."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from vdagent_agentkit.mcp_client import McpTool, ToolOutcome
from vdagent_backend.mcp import re_sql
from vdagent_backend.mcp.sql import SqlError
from vdagent_contracts.envelope import ArtifactDraft
from vdagent_contracts.scope import AuthorizedScope

ALICE = "u_000000000001"
SCOPES = {ALICE: AuthorizedScope(project_ids=["PRJ-X"]), "u_000000000002": AuthorizedScope(project_ids=["PRJ-Y"])}


@dataclass
class DwMcp:
    dw_path: str
    user_id: str = ALICE
    task_id: str = "t_1"
    fail_sql: set[str] = field(default_factory=set)
    delay_s: float = 0.0
    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def list_tools(self) -> list[McpTool]:
        names = ["re_run_query", "get_dataset_rows", "artifact_put", "artifact_get", "artifact_list", "get_user_context"]
        return [McpTool(name=n, description=n, input_schema={}) for n in names]

    @asynccontextmanager
    async def factory(self, url: str, token: str) -> AsyncIterator["DwMcp"]:
        yield self

    def called(self, name: str) -> list[dict[str, Any]]:
        return [a for n, a in self.calls if n == name]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        try:
            result = getattr(self, f"_{name}")(arguments)
        except (SqlError, ValueError, KeyError) as exc:
            return ToolOutcome(text=f"error: {exc}", is_error=True)
        return ToolOutcome(text=json.dumps(result, ensure_ascii=False))

    def _re_run_query(self, args: dict[str, Any]) -> dict[str, Any]:
        if args["sql"] in self.fail_sql:
            raise SqlError("no such column: planted")
        scope = SCOPES.get(self.user_id, AuthorizedScope())
        result, hidden = re_sql.scoped_query(self.dw_path, args["sql"], scope, timeout_s=5.0,
                                             count_hidden=bool(args.get("count_hidden")))
        dataset_id = f"ds_{len(self.datasets) + 1}"
        self.datasets[dataset_id] = {"columns": result.columns, "rows": result.rows}
        out = {"dataset_id": dataset_id, "columns": result.columns, "row_count": len(result.rows),
               "truncated": result.truncated, "preview": result.rows[:20]}
        if hidden is not None:
            out["hidden_rows"] = hidden
        return out

    def _get_dataset_rows(self, args: dict[str, Any]) -> dict[str, Any]:
        data = self.datasets[args["dataset_id"]]
        offset, limit = args.get("offset", 0), args.get("limit", 50)
        return {"rows": data["rows"][offset : offset + limit]}

    def _get_user_context(self, args: dict[str, Any]) -> dict[str, Any]:
        scope = SCOPES.get(self.user_id, AuthorizedScope())
        return {"user_id": self.user_id, "role": "SALES_OPS", "authorized_scope": scope.model_dump()}

    def _artifact_put(self, args: dict[str, Any]) -> dict[str, Any]:
        draft = ArtifactDraft.model_validate(json.loads(args["draft_json"], parse_float=Decimal))
        artifact_id = draft.artifact_id or f"art_{len(self.artifacts) + 1}"
        versions = self.artifacts.setdefault(artifact_id, [])
        stored = {**json.loads(draft.model_dump_json(exclude={"artifact_id"})), "artifact_id": artifact_id,
                  "version": len(versions) + 1, "run_id": args.get("run_id") or self.task_id, "task_id": self.task_id}
        versions.append(stored)
        return stored

    def _artifact_get(self, args: dict[str, Any]) -> dict[str, Any]:
        versions = self.artifacts.get(args["artifact_id"])
        if not versions:
            raise ValueError("artifact not found")
        return versions[args["version"] - 1] if args.get("version") else versions[-1]

    def _artifact_list(self, args: dict[str, Any]) -> dict[str, Any]:
        latest = [v[-1] for v in self.artifacts.values()]
        return {"artifacts": [
            {k: v for k, v in a.items() if k != "payload"} for a in latest
            if (not args.get("run_id") or a["run_id"] == args["run_id"])
            and (not args.get("artifact_type") or a["artifact_type"] == args["artifact_type"])
        ]}
