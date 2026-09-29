"""Per-user SSE fan-out.

`EventBus.publish(user_id, event, data)` delivers to that user's subscribers only. Each subscriber
has a bounded queue (`QUEUE_MAX`); on overflow the subscriber is closed and its stream ends (the
frontend reconnects and refetches). There is no replay.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

QUEUE_MAX = 1000


@dataclass(frozen=True)
class Event:
    """One SSE event: its name (`task.updated`, …) and JSON payload."""

    event: str
    data: dict[str, Any]


_CLOSED = Event("__closed__", {})


@dataclass(eq=False)
class Subscriber:
    """One open SSE stream of one user."""

    user_id: str
    queue: asyncio.Queue[Event] = field(default_factory=lambda: asyncio.Queue(QUEUE_MAX + 1))
    closed: bool = False

    async def next(self) -> Event | None:
        """Next event, or None once the subscriber is closed."""
        if self.closed and self.queue.empty():
            return None
        ev = await self.queue.get()
        return None if ev is _CLOSED else ev


class EventBus:
    """Subscribers by user; `publish` never blocks."""

    def __init__(self) -> None:
        self._subs: dict[str, set[Subscriber]] = {}

    def subscribe(self, user_id: str) -> Subscriber:
        sub = Subscriber(user_id)
        self._subs.setdefault(user_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        subs = self._subs.get(sub.user_id)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subs[sub.user_id]

    def publish(self, user_id: str, event: str, data: dict[str, Any]) -> None:
        """Queue `event` for every subscriber of `user_id`; a full subscriber is closed instead."""
        for sub in list(self._subs.get(user_id, ())):
            self._offer(sub, Event(event, data))

    def _offer(self, sub: Subscriber, ev: Event) -> None:
        if sub.closed:
            return
        if sub.queue.qsize() >= QUEUE_MAX:
            sub.closed = True
            sub.queue.put_nowait(_CLOSED)
            self.unsubscribe(sub)
            return
        sub.queue.put_nowait(ev)
