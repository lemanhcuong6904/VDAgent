"""`ArtifactService`: the only artifact entry point of the REST API, the MCP tools and startup recovery.

Reads of a missing or another user's artifact return `None`; invalid requests raise
`ArtifactError` (or its subclass `ChartError`) with the user-facing text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.artifacts.charts import build_chart_spec
from vdagent_backend.artifacts.envelopes import EnvelopeStore
from vdagent_backend.artifacts.errors import ArtifactError
from vdagent_backend.core import iso_ms, utcnow
from vdagent_backend.artifacts.repository import Artifacts
from vdagent_backend.persistence import tables
from vdagent_backend.warehouse import QueryResult
from vdagent_contracts.envelope import ArtifactDraft, ArtifactEnvelope, ArtifactStatus, Producer

_EMBED = re.compile(r"\{\{\s*(chart|dataset)\s*:\s*([^}\s]+)\s*\}\}")
_SPEC_EMBED = re.compile(r"\{\{\s*chart_spec\s*:\s*([^}\s]+)\s*\}\}")
RESTARTED = "backend restarted"


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
        self._envelopes = EnvelopeStore(db)

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
            ArtifactError: The markdown embeds (`{{chart:<id>}}`, `{{dataset:<id>}}`, `{{chart_spec:<id>@<v>}}`)
                an id that is unknown or another user's (or a chart_spec embed without a pinned version).
        """
        refs: dict[str, set[str]] = {"chart": set(), "dataset": set()}
        for kind, artifact_id in _EMBED.findall(markdown):
            refs[kind].add(artifact_id)
        missing: set[str] = set()
        for kind, table in (("chart", tables.charts), ("dataset", tables.datasets)):
            missing |= refs[kind] - await self._repo.existing_ids(user_id, table, refs[kind])
        if missing:
            raise ArtifactError(f"markdown references unknown ids: {', '.join(sorted(missing))}")
        for ref in _SPEC_EMBED.findall(markdown):  # {{chart_spec:<id>@<version>}}: a pinned chart_spec of this user
            artifact_id, _, version = ref.partition("@")
            if not version.isdigit():
                raise ArtifactError(f"chart_spec embed {ref!r} must pin a version: {{{{chart_spec:<id>@<version>}}}}")
            envelope = await self._envelopes.get(user_id, artifact_id, version=int(version))
            if envelope is None or envelope.artifact_type.value != "chart_spec":
                raise ArtifactError(f"markdown references an unknown chart_spec: {ref}")
        return await self._repo.insert_report(user_id=user_id, invocation_id=invocation_id, title=title, markdown=markdown)

    async def list_reports(self, user_id: str) -> list[dict[str, Any]]:
        """`[{id, title, created_at}]`, newest first."""
        return await self._repo.list_reports(user_id)

    async def get_report(self, user_id: str, report_id: str) -> dict[str, Any] | None:
        """`{id, title, markdown, created_at}`."""
        return await self._repo.get_report(user_id, report_id)

    # ------------------------------------------------------------------ artifact envelopes (six-agent DAG)

    async def put_envelope(self, user_id: str, run_id: str, task_id: str, draft: ArtifactDraft) -> ArtifactEnvelope:
        """Store an envelope draft (a new artifact or the next version of `draft.artifact_id`).

        Raises:
            EnvelopeError: The store refuses the draft (see `EnvelopeStore.put`).
        """
        return await self._envelopes.put(user_id=user_id, run_id=run_id, task_id=task_id, draft=draft)

    async def get_envelope(self, user_id: str, artifact_id: str, version: int | None = None) -> ArtifactEnvelope | None:
        """One version (the latest by default), or None if unknown to this user."""
        return await self._envelopes.get(user_id, artifact_id, version=version)

    async def list_envelopes(
        self, user_id: str, run_id: str | None = None, artifact_type: str | None = None
    ) -> list[ArtifactEnvelope]:
        """Latest version of each of the user's envelopes, oldest first, optionally filtered."""
        return await self._envelopes.list_artifacts(user_id, run_id=run_id, artifact_type=artifact_type)

    async def get_chart_spec(self, user_id: str, artifact_id: str, version: int) -> dict[str, Any] | None:
        """`{id, version, title, chart_type, spec}` of a pinned chart_spec of this user; None if unknown or not one.

        Raises:
            ArtifactError: The chart_spec holds no Vega-Lite specification.
        """
        envelope = await self._envelopes.get(user_id, artifact_id, version=version)
        if envelope is None or envelope.artifact_type.value != "chart_spec":
            return None
        spec = envelope.payload.get("vega_lite")
        if not isinstance(spec, dict):
            raise ArtifactError("chart_spec has no Vega-Lite specification")
        plotly = envelope.payload.get("plotly")
        return {
            "id": envelope.artifact_id,
            "version": envelope.version,
            "title": envelope.payload.get("title") or envelope.artifact_id,
            "chart_type": envelope.payload.get("chart_type"),
            "spec": spec,
            "plotly": plotly if isinstance(plotly, dict) else None,
        }

    async def interrupt_run(self, user_id: str, task_id: str) -> list[ArtifactEnvelope]:
        """Startup recovery of a task the restart failed (WS7 F-04): each of its run_states still `running`/`pending`
        gets a new `interrupted` version (history kept); running/pending steps become `interrupted`.

        No automatic resume: the interrupted turn's MCP tokens and pending calls are gone; the user re-asks.
        Returns the new versions.
        """
        written: list[ArtifactEnvelope] = []
        for state in await self._envelopes.list_artifacts(user_id, run_id=task_id, artifact_type="run_state"):
            if state.payload.get("status") not in ("running", "pending"):
                continue
            steps = [{**step, "status": "interrupted"} if step.get("status") in ("running", "pending") else step
                     for step in state.payload.get("steps", [])]
            draft = ArtifactDraft(
                artifact_id=state.artifact_id, artifact_type=state.artifact_type, schema_version=state.schema_version,
                status=ArtifactStatus.INVALID, producer=Producer(agent="backend", agent_version="recovery"),
                snapshot_refs=state.snapshot_refs, semantic_config_version=state.semantic_config_version,
                limitations=[f"INTERRUPTED:{RESTARTED}"], reason_code="BACKEND_RESTARTED",
                reason="backend restarted during the run",
                payload={**state.payload, "status": "interrupted", "steps": steps,
                         "interrupted": {"reason": RESTARTED, "at": iso_ms(utcnow())}},
            )
            written.append(await self._envelopes.put(user_id=user_id, run_id=task_id, task_id=task_id, draft=draft))
        return written
