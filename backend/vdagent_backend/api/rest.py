"""REST endpoints (§10)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

from vdagent_backend.api.deps import Svc, UserId
from vdagent_backend.api.errors import ApiError, not_found
from vdagent_backend.db import artifact_store, artifacts, repo
from vdagent_backend.engine import IdempotencyConflictError, TaskFinishedError, TaskNotFoundError, UnknownAgentError

router = APIRouter(prefix="/api")

TASK_STATUSES = ("running", "completed", "failed", "cancelled")


class NewUser(BaseModel):
    name: str = Field(min_length=1)


class NewMessage(BaseModel):
    content: str


def _unknown_agent(agent: str) -> ApiError:
    return ApiError(404, "unknown_agent", f"unknown agent '{agent}'")


# --------------------------------------------------------------------------- users


@router.get("/users")
async def list_users(svc: Svc) -> list[dict[str, Any]]:
    return [repo.user_dto(u) for u in await repo.list_users(svc.db)]


@router.post("/users", status_code=201)
async def create_user(svc: Svc, body: NewUser) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_request", "name must not be empty")
    return repo.user_dto(await repo.create_user(svc.db, name))


# --------------------------------------------------------------------------- agents + chats


@router.get("/agents")
async def list_agents(svc: Svc, user_id: UserId) -> list[dict[str, Any]]:
    return svc.engine.agents(user_id)


@router.get("/agents/{agent}/messages")
async def get_messages(
    svc: Svc,
    user_id: UserId,
    agent: str,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    if agent not in svc.engine.registry:
        raise _unknown_agent(agent)
    rows = await repo.messages_page(svc.db, user_id, agent, before_seq, limit)
    return {
        "summary": await repo.get_summary(svc.db, user_id, agent),
        "messages": [repo.message_dto(r) for r in rows],
        "pending": svc.engine.pending(user_id, agent),
    }


@router.post("/agents/{agent}/messages", status_code=202)
async def post_message(
    svc: Svc, user_id: UserId, agent: str, body: NewMessage, response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> dict[str, Any]:
    """Start a task. WS7 F-11: an optional `Idempotency-Key` makes retries return the first task (200, deduplicated)."""
    content = body.content.strip()
    if not content:
        raise ApiError(422, "invalid_request", "content must not be empty")
    key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    try:
        task, inv = await svc.engine.post_message(user_id, agent, content, key)
    except UnknownAgentError:
        raise _unknown_agent(agent) from None
    except IdempotencyConflictError:
        raise ApiError(409, "idempotency_conflict", "Idempotency-Key already used with different content") from None
    deduplicated = bool(task.get("deduplicated"))
    if deduplicated:
        response.status_code = 200
    return {"task_id": task["id"], "invocation_id": inv["id"], "deduplicated": deduplicated}


# --------------------------------------------------------------------------- tasks


@router.get("/tasks")
async def list_tasks(
    svc: Svc, user_id: UserId, status: Annotated[str | None, Query()] = None
) -> list[dict[str, Any]]:
    if status is not None and status not in TASK_STATUSES:
        raise ApiError(422, "invalid_request", f"status must be one of {', '.join(TASK_STATUSES)}")
    return [repo.task_dto(t) for t in await repo.list_tasks(svc.db, user_id, status)]


@router.get("/tasks/{task_id}")
async def get_task(svc: Svc, user_id: UserId, task_id: str) -> dict[str, Any]:
    task = await repo.get_task(svc.db, task_id, user_id)
    if task is None:
        raise not_found("task")
    invocations = await repo.list_task_invocations(svc.db, task_id)
    return {"task": repo.task_dto(task), "invocations": [repo.invocation_dto(i) for i in invocations]}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(svc: Svc, user_id: UserId, task_id: str) -> dict[str, Any]:
    try:
        task = await svc.engine.cancel_task(user_id, task_id)
    except TaskNotFoundError:
        raise not_found("task") from None
    except TaskFinishedError:
        raise ApiError(409, "task_finished", "task already finished") from None
    return {"task": repo.task_dto(task)}


# --------------------------------------------------------------------------- artifacts


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    svc: Svc,
    user_id: UserId,
    dataset_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    ds = await artifacts.get_dataset(svc.db, user_id, dataset_id)
    if ds is None:
        raise not_found("dataset")
    return {
        "id": ds["id"],
        "name": ds["name"],
        "columns": ds["columns"],
        "row_count": ds["row_count"],
        "truncated": ds["truncated"],
        "source_sql": ds["source_sql"],
        "rows": ds["rows"][offset : offset + limit],
    }


@router.get("/charts/{chart_id}")
async def get_chart(svc: Svc, user_id: UserId, chart_id: str) -> dict[str, Any]:
    chart = await artifacts.get_chart(svc.db, user_id, chart_id)
    if chart is None:
        raise not_found("chart")
    return chart


@router.get("/chart-specs/{artifact_id}/{version}")
async def get_chart_spec(svc: Svc, user_id: UserId, artifact_id: str, version: int) -> dict[str, Any]:
    envelope = await artifact_store.get(svc.db, user_id, artifact_id, version=version)
    if envelope is None or envelope.artifact_type.value != "chart_spec":
        raise not_found("chart_spec")
    payload = envelope.payload
    spec = payload.get("vega_lite")
    if not isinstance(spec, dict):
        raise ApiError(422, "invalid_chart_spec", "chart_spec has no Vega-Lite specification")
    return {"id": envelope.artifact_id, "version": envelope.version,
            "title": payload.get("title") or envelope.artifact_id,
            "chart_type": payload.get("chart_type"), "spec": spec}

@router.get("/reports")
async def list_reports(svc: Svc, user_id: UserId) -> list[dict[str, Any]]:
    return await artifacts.list_reports(svc.db, user_id)


@router.get("/reports/{report_id}")
async def get_report(svc: Svc, user_id: UserId, report_id: str) -> dict[str, Any]:
    report = await artifacts.get_report(svc.db, user_id, report_id)
    if report is None:
        raise not_found("report")
    return report
