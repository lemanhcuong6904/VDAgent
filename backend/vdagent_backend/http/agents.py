"""`/api/agents`: the agent list and each agent's chat (the user's stack with that agent)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel

from vdagent_backend.conversations import message_dto
from vdagent_backend.http.deps import Svc, UserId
from vdagent_backend.http.errors import ApiError
from vdagent_backend.runtime import IdempotencyConflictError, UnknownAgentError

router = APIRouter(prefix="/api")


class NewMessage(BaseModel):
    """Body of `POST /api/agents/{agent}/messages`."""

    content: str


def _unknown_agent(agent: str) -> ApiError:
    return ApiError(404, "unknown_agent", f"unknown agent '{agent}'")


@router.get("/agents")
async def list_agents(svc: Svc, user_id: UserId) -> list[dict[str, Any]]:
    """Every loaded agent with the caller's stack status."""
    return svc.engine.agents(user_id)


@router.get("/agents/{agent}/messages")
async def get_messages(
    svc: Svc,
    user_id: UserId,
    agent: str,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """A page of the caller's chat with `agent` (newest `limit` before `before_seq`), its summary and queued inbound messages."""
    if agent not in svc.engine.registry:
        raise _unknown_agent(agent)
    rows = await svc.messages.messages_page(user_id, agent, before_seq, limit)
    return {
        "summary": await svc.messages.get_summary(user_id, agent),
        "messages": [message_dto(r) for r in rows],
        "pending": svc.engine.pending(user_id, agent),
    }


@router.post("/agents/{agent}/messages", status_code=202)
async def post_message(
    svc: Svc,
    user_id: UserId,
    agent: str,
    body: NewMessage,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> dict[str, Any]:
    """Start a task: the message goes to `agent`'s stack (queued if the agent is busy).

    An optional `Idempotency-Key` makes a retry return the first task (`200`, `deduplicated: true`) instead of running
    again; the same key with other content is `409 idempotency_conflict` (WS7 F-11).
    """
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
