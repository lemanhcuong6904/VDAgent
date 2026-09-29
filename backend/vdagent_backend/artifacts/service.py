"""`ArtifactService`: the only artifact entry point of the REST API and the MCP tools.

Reads of a missing or another user's artifact return `None`; invalid requests raise
`ArtifactError` (or its subclass `ChartError`) with the user-facing text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.artifacts.charts import build_chart_spec
from vdagent_backend.artifacts.errors import ArtifactError
from vdagent_backend.artifacts.repository import Artifacts
from vdagent_backend.persistence import tables
from vdagent_backend.warehouse import QueryResult

_EMBED = re.compile(r"\{\{\s*(chart|dataset)\s*:\s*([^}\s]+)\s*\}\}")


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


class ArtifactService:
    """Stores and reads datasets, charts and reports for both transports."""

    def __init__(self, db: AsyncEngine) -> None:
        self._repo = Artifacts(db)

    # ------------------------------------------------------------------ datasets

    async def store_dataset(
        self, user_id: str, invocation_id: str, name: str | None, source_sql: str, result: QueryResult
    ) -> str:
        """Store a query result as a new dataset of `user_id`; returns its id."""
        return await self._repo.insert_dataset(
            user_id=user_id,
            invocation_id=invocation_id,
            name=name,
            source_sql=source_sql,
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
        )

    async def get_dataset(self, user_id: str, dataset_id: str) -> dict[str, Any] | None:
        """Metadata and all rows."""
        return await self._repo.get_dataset(user_id, dataset_id)

    async def datasets(self, user_id: str, dataset_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Every listed dataset with all rows, in order.

        Raises:
            ArtifactError: `dataset not found: <id>` for the first id that is unknown or another user's.
        """
        found = await self._repo.get_datasets(user_id, dataset_ids)
        loaded = {d["id"] for d in found}
        missing = next((i for i in dataset_ids if i not in loaded), None)
        if missing is not None:
            raise ArtifactError(f"dataset not found: {missing}")
        return found

    async def describe_dataset(self, user_id: str, dataset_id: str) -> dict[str, Any] | None:
        """`{dataset_id, name, row_count, truncated, source_sql, columns: [{name, type, min, max, null_count}]}`."""
        dataset = await self._repo.get_dataset(user_id, dataset_id)
        if dataset is None:
            return None
        return {
            "dataset_id": dataset["id"],
            "name": dataset["name"],
            "row_count": dataset["row_count"],
            "truncated": dataset["truncated"],
            "source_sql": dataset["source_sql"],
            "columns": _column_stats(dataset),
        }

    async def dataset_page(self, user_id: str, dataset_id: str, offset: int, limit: int) -> dict[str, Any] | None:
        """Metadata plus `rows`, the rows `offset … offset + limit - 1`."""
        meta = await self._repo.get_dataset_meta(user_id, dataset_id)
        if meta is None:
            return None
        return {**meta, "rows": await self._repo.get_rows(user_id, dataset_id, offset, limit)}

    # ------------------------------------------------------------------ charts

    async def create_chart(
        self, user_id: str, invocation_id: str, dataset_id: str, kind: str, x: str, y: list[str], title: str
    ) -> str | None:
        """Build and store a Vega-Lite chart of a dataset; its id, or None if the dataset is not found.

        Raises:
            ChartError: The kind or the columns do not fit the dataset.
        """
        dataset = await self._repo.get_dataset(user_id, dataset_id)
        if dataset is None:
            return None
        spec = build_chart_spec(dataset, kind, x, y, title)
        return await self._repo.insert_chart(
            user_id=user_id, invocation_id=invocation_id, dataset_id=dataset_id, title=title, spec=spec
        )

    async def get_chart(self, user_id: str, chart_id: str) -> dict[str, Any] | None:
        """`{id, title, dataset_id, spec}`."""
        return await self._repo.get_chart(user_id, chart_id)

    # ------------------------------------------------------------------ reports

    async def save_report(self, user_id: str, invocation_id: str, title: str, markdown: str) -> str:
        """Store a markdown report; returns its id.

        Raises:
            ArtifactError: The markdown embeds (`{{chart:<id>}}`, `{{dataset:<id>}}`) an id that is
                unknown or another user's.
        """
        refs: dict[str, set[str]] = {"chart": set(), "dataset": set()}
        for kind, artifact_id in _EMBED.findall(markdown):
            refs[kind].add(artifact_id)
        missing: set[str] = set()
        for kind, table in (("chart", tables.charts), ("dataset", tables.datasets)):
            missing |= refs[kind] - await self._repo.existing_ids(user_id, table, refs[kind])
        if missing:
            raise ArtifactError(f"markdown references unknown ids: {', '.join(sorted(missing))}")
        return await self._repo.insert_report(user_id=user_id, invocation_id=invocation_id, title=title, markdown=markdown)

    async def list_reports(self, user_id: str) -> list[dict[str, Any]]:
        """`[{id, title, created_at}]`, newest first."""
        return await self._repo.list_reports(user_id)

    async def get_report(self, user_id: str, report_id: str) -> dict[str, Any] | None:
        """`{id, title, markdown, created_at}`."""
        return await self._repo.get_report(user_id, report_id)
