"""S5 execute (build spec 02 §5): one validated SELECT through MCP `re_run_query`, rows paged back into the harness.

Rows stay in the harness: the LLM only ever gets `for_llm()` (row count, columns, nulls, min/max). A SQL error goes
back to the generator with the error text, at most `max_rounds` fixes per query.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from vdagent_agentkit.mcp_client import McpSession

PAGE_ROWS = 200  # MCP get_dataset_rows maximum


@dataclass(frozen=True)
class QueryOutcome:
    sql: str
    dataset_id: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    hidden_rows: int | None = None
    fix_rounds: int = 0

    def records(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def for_llm(self) -> dict[str, Any]:
        """Metadata and a per-column profile; never the rows themselves."""
        profile = []
        for i, name in enumerate(self.columns):
            values = [row[i] for row in self.rows if row[i] is not None]
            comparable = [v for v in values if isinstance(v, (int, str))]
            same_type = comparable and all(type(v) is type(comparable[0]) for v in comparable)
            profile.append(
                {
                    "name": name,
                    "nulls": len(self.rows) - len(values),
                    "distinct": len({json.dumps(v) for v in values}),
                    "min": min(comparable) if same_type else None,
                    "max": max(comparable) if same_type else None,
                }
            )
        return {"dataset_id": self.dataset_id, "row_count": len(self.rows), "truncated": self.truncated, "columns": profile}


@dataclass(frozen=True)
class SqlFailure:
    sql: str
    error: str
    rounds: int = 0
    history: list[str] = field(default_factory=list)


async def _call(session: McpSession, name: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
    outcome = await session.call_tool(name, arguments)
    if outcome.is_error:
        return False, outcome.text
    return True, json.loads(outcome.text)


async def execute(session: McpSession, sql: str, *, name: str | None = None, count_hidden: bool = False) -> QueryOutcome | SqlFailure:
    args: dict[str, Any] = {"sql": sql}
    if name:
        args["name"] = name
    if count_hidden:
        args["count_hidden"] = True
    ok, result = await _call(session, "re_run_query", args)
    if not ok:
        return SqlFailure(sql=sql, error=str(result))
    dataset_id, total = result["dataset_id"], result["row_count"]
    rows: list[list[Any]] = []
    while len(rows) < total:
        ok, page = await _call(session, "get_dataset_rows", {"dataset_id": dataset_id, "offset": len(rows), "limit": PAGE_ROWS})
        if not ok or not page["rows"]:
            return SqlFailure(sql=sql, error=f"could not read dataset {dataset_id}: {page if not ok else 'empty page'}")
        rows.extend(page["rows"])
    return QueryOutcome(
        sql=sql,
        dataset_id=dataset_id,
        columns=[c["name"] for c in result["columns"]],
        rows=rows,
        truncated=bool(result["truncated"]),
        hidden_rows=result.get("hidden_rows"),
    )


Fixer = Callable[[str, str], Awaitable[str]]


async def run_with_fixes(
    session: McpSession, sql: str, *, fixer: Fixer, max_rounds: int = 2, name: str | None = None, count_hidden: bool = False
) -> QueryOutcome | SqlFailure:
    """Execute; on a SQL error ask `fixer(sql, error)` for a new query, at most `max_rounds` times."""
    history: list[str] = []
    current = sql
    for round_no in range(max_rounds + 1):
        outcome = await execute(session, current, name=name, count_hidden=count_hidden)
        if isinstance(outcome, QueryOutcome):
            return QueryOutcome(**{**outcome.__dict__, "fix_rounds": round_no})
        history.append(outcome.error)
        if round_no == max_rounds:
            return SqlFailure(sql=current, error=outcome.error, rounds=round_no, history=history)
        current = await fixer(current, outcome.error)
    raise AssertionError("unreachable")
