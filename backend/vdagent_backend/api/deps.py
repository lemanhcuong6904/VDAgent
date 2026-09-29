"""Shared request dependencies: app services and `X-User-Id` identity (§10, D10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.api.errors import ApiError
from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.config import Config
from vdagent_backend.conversations import Users
from vdagent_backend.runtime import Engine
from vdagent_backend.core import EventBus


@dataclass
class Services:
    cfg: Config
    db: AsyncEngine
    bus: EventBus
    engine: Engine
    artifacts: ArtifactService


def services(request: Request) -> Services:
    return request.app.state.services


async def resolve_user(db: AsyncEngine, user_id: str | None) -> str:
    if not user_id or await Users(db).get_user(user_id) is None:
        raise ApiError(401, "unknown_user", "unknown or missing user")
    return user_id


async def current_user(
    svc: Annotated[Services, Depends(services)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    return await resolve_user(svc.db, x_user_id)


Svc = Annotated[Services, Depends(services)]
UserId = Annotated[str, Depends(current_user)]
