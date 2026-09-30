"""Stored stack messages as model history, and the tool calls a crashed turn left unanswered."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from vdagent_sdk import Message


def to_message(row: Mapping[str, Any]) -> Message:
    """A stored message as OpenAI-shaped history; inbound messages read `[from: <sender>] <text>`."""
    role = row["role"]
    if role == "user":
        return {"role": "user", "content": f"[from: {row['sender']}] {row['content']}"}
    if role == "assistant":
        calls = row["tool_calls_json"] or []
        if not calls:
            return {"role": "assistant", "content": row["content"]}
        return {
            "role": "assistant",
            "content": row["content"] or None,
            "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments_json"]}}
                for c in calls
            ],
        }
    return {"role": "tool", "tool_call_id": row["tool_call_id"] or "", "content": row["content"]}


def missing_tool_results(messages: Iterable[Mapping[str, Any]]) -> list[str]:
    """Ids of the assistant tool calls in `messages` that have no tool result, in call order."""
    rows = list(messages)
    answered = {m["tool_call_id"] for m in rows if m["role"] == "tool"}
    missing = [
        call["id"]
        for m in rows
        if m["role"] == "assistant" and m["tool_calls_json"]
        for call in m["tool_calls_json"]
        if call["id"] not in answered
    ]
    return list(dict.fromkeys(missing))
