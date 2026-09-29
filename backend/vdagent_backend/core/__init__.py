"""Shared building blocks with no Backend dependencies: ids, clock, errors, SSE bus, MCP tokens.

May import: nothing from `vdagent_backend`.
"""

from vdagent_backend.core.clock import iso_ms, utcnow
from vdagent_backend.core.errors import describe, error_body
from vdagent_backend.core.events import Event, EventBus, Subscriber
from vdagent_backend.core.ids import new_id
from vdagent_backend.core.tokens import McpIdentity, TokenRegistry

__all__ = [
    "Event",
    "EventBus",
    "McpIdentity",
    "Subscriber",
    "TokenRegistry",
    "describe",
    "error_body",
    "iso_ms",
    "new_id",
    "utcnow",
]
