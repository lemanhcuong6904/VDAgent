"""SSE events of the runtime, built from repository rows with the conversation DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vdagent_backend.conversations import invocation_dto, message_dto, task_dto
from vdagent_backend.core import EventBus


class Publisher:
    """Publishes `task.updated`, `invocation.updated`, `message.appended` and `agent.status`."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def task(self, row: Mapping[str, Any]) -> None:
        self._bus.publish(row["user_id"], "task.updated", {"task": task_dto(row)})

    def invocation(self, row: Mapping[str, Any]) -> None:
        self._bus.publish(row["user_id"], "invocation.updated", {"invocation": invocation_dto(row)})

    def message(self, row: Mapping[str, Any]) -> None:
        self._bus.publish(row["user_id"], "message.appended", {"agent": row["agent"], "message": message_dto(row)})

    def status(self, user_id: str, status: dict[str, Any]) -> None:
        """`status` is `{agent, busy, queue_len}` of one stack."""
        self._bus.publish(user_id, "agent.status", status)
