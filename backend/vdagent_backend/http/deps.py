"""Request dependencies: the app's `Services` and the caller identity from `X-User-Id`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from vdagent_backend.artifacts import ArtifactService
from vdagent_backend.conversations import Messages, Tasks, Users
from vdagent_backend.core import EventBus
from vdagent_backend.http.errors import ApiError
from vdagent_backend.runtime import Engine


@dataclass
class Services:
    """Everything a request handler needs; built once by the app lifespan (`app.state.services`)."""

    users: Users
    tasks: Tasks
    messages: Messages
    artifacts: ArtifactService
    engine: Engine
    bus: EventBus


def services(request: Request) -> Services:
    """The app's `Services`."""
    return request.app.state.services


async def resolve_user(users: Users, user_id: str | None) -> str:
    """`user_id` if it names a user; otherwise `401 unknown_user`."""
    if not user_id or await users.get_user(user_id) is None:
        raise ApiError(401, "unknown_user", "unknown or missing user")
    return user_id


async def current_user(
    svc: Annotated[Services, Depends(services)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """The `X-User-Id` header, if it names a user; otherwise `401 unknown_user`."""
    return await resolve_user(svc.users, x_user_id)


Svc = Annotated[Services, Depends(services)]
UserId = Annotated[str, Depends(current_user)]
