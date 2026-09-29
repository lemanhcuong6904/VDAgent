"""REST endpoints (§10)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from vdagent_backend.api.deps import Svc, UserId
from vdagent_backend.api.errors import ApiError, not_found
from vdagent_backend.artifacts import Artifacts
from vdagent_backend.conversations import TASK_STATUSES, Messages, Tasks, Users, invocation_dto, message_dto, task_dto, user_dto
from vdagent_backend.engine import TaskFinishedError, TaskNotFoundError, UnknownAgentError

router = APIRouter(prefix="/api")

class NewUser(BaseModel):
    name: str = Field(min_length=1)


class NewMessage(BaseModel):
    content: str


def _unknown_agent(agent: str) -> ApiError:
    return ApiError(404, "unknown_agent", f"unknown agent '{agent}'")


# --------------------------------------------------------------------------- users


@router.get("/users")
async def list_users(svc: Svc) -> list[dict[str, Any]]:
    return [user_dto(u) for u in await Users(svc.db).list_users()]


@router.post("/users", status_code=201)
async def create_user(svc: Svc, body: NewUser) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_request", "name must not be empty")
    return user_dto(await Users(svc.db).create_user(name))


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
    rows = await Messages(svc.db).messages_page(user_id, agent, before_seq, limit)
    return {
        "summary": await Messages(svc.db).get_summary(user_id, agent),
        "messages": [message_dto(r) for r in rows],
        "pending": svc.engine.pending(user_id, agent),
    }


@router.post("/agents/{agent}/messages", status_code=202)
async def post_message(svc: Svc, user_id: UserId, agent: str, body: NewMessage) -> dict[str, str]:
    content = body.content.strip()
    if not content:
        raise ApiError(422, "invalid_request", "content must not be empty")
    try:
        task, inv = await svc.engine.post_message(user_id, agent, content)
    except UnknownAgentError:
        raise _unknown_agent(agent) from None
    return {"task_id": task["id"], "invocation_id": inv["id"]}


# --------------------------------------------------------------------------- tasks


@router.get("/tasks")
async def list_tasks(
    svc: Svc, user_id: UserId, status: Annotated[str | None, Query()] = None
) -> list[dict[str, Any]]:
    if status is not None and status not in TASK_STATUSES:
        raise ApiError(422, "invalid_request", f"status must be one of {', '.join(TASK_STATUSES)}")
    return [task_dto(t) for t in await Tasks(svc.db).list_tasks(user_id, status)]


@router.get("/tasks/{task_id}")
async def get_task(svc: Svc, user_id: UserId, task_id: str) -> dict[str, Any]:
    task = await Tasks(svc.db).get_task(task_id, user_id)
    if task is None:
        raise not_found("task")
    invocations = await Tasks(svc.db).list_task_invocations(task_id)
    return {"task": task_dto(task), "invocations": [invocation_dto(i) for i in invocations]}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(svc: Svc, user_id: UserId, task_id: str) -> dict[str, Any]:
    try:
        task = await svc.engine.cancel_task(user_id, task_id)
    except TaskNotFoundError:
        raise not_found("task") from None
    except TaskFinishedError:
        raise ApiError(409, "task_finished", "task already finished") from None
    return {"task": task_dto(task)}


# --------------------------------------------------------------------------- artifacts


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    svc: Svc,
    user_id: UserId,
    dataset_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    ds = await Artifacts(svc.db).get_dataset(user_id, dataset_id)
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
    chart = await Artifacts(svc.db).get_chart(user_id, chart_id)
    if chart is None:
        raise not_found("chart")
    return chart


@router.get("/reports")
async def list_reports(svc: Svc, user_id: UserId) -> list[dict[str, Any]]:
    return await Artifacts(svc.db).list_reports(user_id)


@router.get("/reports/{report_id}")
async def get_report(svc: Svc, user_id: UserId, report_id: str) -> dict[str, Any]:
    report = await Artifacts(svc.db).get_report(user_id, report_id)
    if report is None:
        raise not_found("report")
    return report
