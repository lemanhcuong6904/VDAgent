"""`/api/tasks`: the user's tasks, one task with its invocations, and cancel."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from vdagent_backend.conversations import TASK_STATUSES, invocation_dto, task_dto
from vdagent_backend.http.deps import Svc, UserId
from vdagent_backend.http.errors import ApiError, not_found
from vdagent_backend.runtime import TaskFinishedError, TaskNotFoundError

router = APIRouter(prefix="/api")


@router.get("/tasks")
async def list_tasks(svc: Svc, user_id: UserId, status: Annotated[str | None, Query()] = None) -> list[dict[str, Any]]:
    """The caller's tasks, newest first, optionally of one status."""
    if status is not None and status not in TASK_STATUSES:
        raise ApiError(422, "invalid_request", f"status must be one of {', '.join(TASK_STATUSES)}")
    return [task_dto(t) for t in await svc.tasks.list_tasks(user_id, status)]


@router.get("/tasks/{task_id}")
async def get_task(svc: Svc, user_id: UserId, task_id: str) -> dict[str, Any]:
    """A task with its invocations in creation order."""
    task = await svc.tasks.get_task(task_id, user_id)
    if task is None:
        raise not_found("task")
    invocations = await svc.tasks.list_task_invocations(task_id)
    return {"task": task_dto(task), "invocations": [invocation_dto(i) for i in invocations]}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(svc: Svc, user_id: UserId, task_id: str) -> dict[str, Any]:
    """Cancel a running task; `409 task_finished` if it already finished."""
    try:
        task = await svc.engine.cancel_task(user_id, task_id)
    except TaskNotFoundError:
        raise not_found("task") from None
    except TaskFinishedError:
        raise ApiError(409, "task_finished", "task already finished") from None
    return {"task": task_dto(task)}
