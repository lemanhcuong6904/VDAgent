"""REST/SSE shapes of users, tasks, invocations and messages, built from repository rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def user_dto(row: Mapping[str, Any]) -> dict[str, Any]:
    """`{id, name}`."""
    return {"id": row["id"], "name": row["name"]}


def task_dto(row: Mapping[str, Any]) -> dict[str, Any]:
    """`{id, root_agent, status, created_at, finished_at}`."""
    return {
        "id": row["id"],
        "root_agent": row["root_agent"],
        "status": row["status"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


_INVOCATION_FIELDS = (
    "id", "task_id", "agent", "caller", "parent_id", "tool_call_id", "depth", "inbound_text",
    "status", "result_text", "error", "created_at", "started_at", "finished_at",
)  # fmt: skip


def invocation_dto(row: Mapping[str, Any]) -> dict[str, Any]:
    """An invocation row without `user_id`."""
    return {k: row[k] for k in _INVOCATION_FIELDS}


def message_dto(row: Mapping[str, Any]) -> dict[str, Any]:
    """A stack message with `tool_calls` decoded (None without calls) and `compacted` as a bool."""
    return {
        "id": row["id"],
        "seq": row["seq"],
        "task_id": row["task_id"],
        "invocation_id": row["invocation_id"],
        "role": row["role"],
        "sender": row["sender"],
        "content": row["content"],
        "tool_calls": row["tool_calls_json"] or None,
        "tool_call_id": row["tool_call_id"],
        "compacted": row["compacted"],
        "created_at": row["created_at"],
    }
