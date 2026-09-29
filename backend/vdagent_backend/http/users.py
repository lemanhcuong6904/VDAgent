"""`/api/users`: list and create users (no identity needed)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from vdagent_backend.conversations import user_dto
from vdagent_backend.http.deps import Svc
from vdagent_backend.http.errors import ApiError

router = APIRouter(prefix="/api")


class NewUser(BaseModel):
    name: str = Field(min_length=1)


@router.get("/users")
async def list_users(svc: Svc) -> list[dict[str, Any]]:
    return [user_dto(u) for u in await svc.users.list_users()]


@router.post("/users", status_code=201)
async def create_user(svc: Svc, body: NewUser) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_request", "name must not be empty")
    return user_dto(await svc.users.create_user(name))
