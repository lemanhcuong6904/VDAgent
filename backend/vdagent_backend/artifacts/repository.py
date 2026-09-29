"""The `datasets`, `charts` and `reports` tables.

Every read is scoped by the owning user (user isolation): another user's id reads exactly like an
unknown id (`None`). Writes take the owner and the creating invocation from the MCP caller.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.core import new_id
from vdagent_backend.persistence import fetch_all, fetch_one, tables

_datasets = tables.datasets
_charts = tables.charts
_reports = tables.reports


class Artifacts:
    def __init__(self, db: AsyncEngine) -> None:
        self._db = db

    async def insert_dataset(
        self,
        *,
        user_id: str,
        invocation_id: str,
        name: str | None,
        source_sql: str,
        columns: list[dict[str, str]],
        rows: list[list[Any]],
        truncated: bool,
    ) -> str:
        dataset_id = new_id("ds")
        async with self._db.begin() as conn:
            await conn.execute(
                _datasets.insert().values(
                    id=dataset_id,
                    user_id=user_id,
                    invocation_id=invocation_id,
                    name=name,
                    source_sql=source_sql,
                    columns_json=columns,
                    rows_json=rows,
                    row_count=len(rows),
                    truncated=truncated,
                )
            )
        return dataset_id

    async def get_dataset(self, user_id: str, dataset_id: str) -> dict[str, Any] | None:
        """Metadata and all rows: `{id, name, columns, row_count, truncated, source_sql, rows, created_at}`."""
        row = await fetch_one(
            self._db, select(_datasets).where(_datasets.c.id == dataset_id, _datasets.c.user_id == user_id)
        )
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "columns": row["columns_json"],
            "row_count": row["row_count"],
            "truncated": row["truncated"],
            "source_sql": row["source_sql"],
            "rows": row["rows_json"],
            "created_at": row["created_at"],
        }

    async def insert_chart(
        self, *, user_id: str, invocation_id: str, dataset_id: str, title: str, spec: dict[str, Any]
    ) -> str:
        chart_id = new_id("ch")
        async with self._db.begin() as conn:
            await conn.execute(
                _charts.insert().values(
                    id=chart_id,
                    user_id=user_id,
                    invocation_id=invocation_id,
                    dataset_id=dataset_id,
                    title=title,
                    spec_json=spec,
                )
            )
        return chart_id

    async def get_chart(self, user_id: str, chart_id: str) -> dict[str, Any] | None:
        """`{id, title, dataset_id, spec}`."""
        row = await fetch_one(
            self._db,
            select(_charts.c.id, _charts.c.title, _charts.c.dataset_id, _charts.c.spec_json).where(
                _charts.c.id == chart_id, _charts.c.user_id == user_id
            ),
        )
        if row is None:
            return None
        return {"id": row["id"], "title": row["title"], "dataset_id": row["dataset_id"], "spec": row["spec_json"]}

    async def insert_report(self, *, user_id: str, invocation_id: str, title: str, markdown: str) -> str:
        report_id = new_id("rp")
        async with self._db.begin() as conn:
            await conn.execute(
                _reports.insert().values(
                    id=report_id, user_id=user_id, invocation_id=invocation_id, title=title, markdown=markdown
                )
            )
        return report_id

    async def list_reports(self, user_id: str) -> list[dict[str, Any]]:
        """`[{id, title, created_at}]`, newest first."""
        return await fetch_all(
            self._db,
            select(_reports.c.id, _reports.c.title, _reports.c.created_at)
            .where(_reports.c.user_id == user_id)
            .order_by(_reports.c.created_at.desc(), _reports.c.id.desc()),
        )

    async def get_report(self, user_id: str, report_id: str) -> dict[str, Any] | None:
        """`{id, title, markdown, created_at}`."""
        return await fetch_one(
            self._db,
            select(_reports.c.id, _reports.c.title, _reports.c.markdown, _reports.c.created_at).where(
                _reports.c.id == report_id, _reports.c.user_id == user_id
            ),
        )

    async def existing_ids(self, user_id: str, table: Table, ids: Collection[str]) -> set[str]:
        """The subset of `ids` that are rows of `table` (`datasets` or `charts`) owned by `user_id`."""
        if not ids:
            return set()
        rows = await fetch_all(
            self._db, select(table.c.id).where(table.c.user_id == user_id, table.c.id.in_(list(ids)))
        )
        return {r["id"] for r in rows}
