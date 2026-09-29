"""`/api/agents`: the agent list and each agent's chat (the user's stack with that agent)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from vdagent_backend.conversations import message_dto
from vdagent_backend.http.deps import Svc, UserId
from vdagent_backend.http.errors import ApiError
from vdagent_backend.runtime import UnknownAgentError

router = APIRouter(prefix="/api")


class NewMessage(BaseModel):
    content: str


def _unknown_agent(agent: str) -> ApiError:
    return ApiError(404, "unknown_agent", f"unknown agent '{agent}'")


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
    rows = await svc.messages.messages_page(user_id, agent, before_seq, limit)
    return {
        "summary": await svc.messages.get_summary(user_id, agent),
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
