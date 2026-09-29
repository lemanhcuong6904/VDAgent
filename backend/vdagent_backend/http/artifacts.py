"""`/api/datasets`, `/api/charts`, `/api/reports`: read the user's artifacts."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from vdagent_backend.http.deps import Svc, UserId
from vdagent_backend.http.errors import not_found

router = APIRouter(prefix="/api")


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    svc: Svc,
    user_id: UserId,
    dataset_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """A dataset's metadata and the rows `offset … offset + limit - 1`."""
    page = await svc.artifacts.dataset_page(user_id, dataset_id, offset, limit)
    if page is None:
        raise not_found("dataset")
    return {
        "id": page["id"],
        "name": page["name"],
        "columns": page["columns"],
        "row_count": page["row_count"],
        "truncated": page["truncated"],
        "source_sql": page["source_sql"],
        "rows": page["rows"],
    }


@router.get("/charts/{chart_id}")
async def get_chart(svc: Svc, user_id: UserId, chart_id: str) -> dict[str, Any]:
    """A chart with its Vega-Lite spec."""
    chart = await svc.artifacts.get_chart(user_id, chart_id)
    if chart is None:
        raise not_found("chart")
    return chart


@router.get("/reports")
async def list_reports(svc: Svc, user_id: UserId) -> list[dict[str, Any]]:
    """The caller's reports, newest first."""
    return await svc.artifacts.list_reports(user_id)


@router.get("/reports/{report_id}")
async def get_report(svc: Svc, user_id: UserId, report_id: str) -> dict[str, Any]:
    """A report with its markdown."""
    report = await svc.artifacts.get_report(user_id, report_id)
    if report is None:
        raise not_found("report")
    return report
