"""The `messages` and `stack_summaries` tables: each (user, agent) stack and its compaction summary.

A stack's `seq` is `max(seq) + 1`, computed inside the INSERT. That is safe because only the run
task holding the stack lock appends to a stack (the stack lock invariant, see `runtime`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import Text, func, literal, select
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.core import utcnow
from vdagent_backend.persistence import Json, Row, UtcTimestamp, fetch_all, fetch_one, tables, upsert, write_returning

_msgs = tables.messages
_summaries = tables.stack_summaries
_tasks = tables.tasks

_APPEND_COLUMNS = (
    "user_id", "agent", "seq", "task_id", "invocation_id", "role", "sender", "content",
    "tool_calls_json", "tool_call_id", "created_at",
)  # fmt: skip


class Messages:
    """Repository of the message stacks and their compaction summaries."""

    def __init__(self, db: AsyncEngine) -> None:
        self._db = db

    async def append_message(
        self,
        *,
        user_id: str,
        agent: str,
        task_id: str,
        invocation_id: str,
        role: str,
        content: str,
        sender: str | None = None,
        tool_calls: Sequence[Mapping[str, str]] | None = None,
        tool_call_id: str | None = None,
    ) -> Row:
        """Append to stack (user_id, agent) with the next `seq`; returns the stored row."""
        values = select(
            literal(user_id),
            literal(agent),
            func.coalesce(func.max(_msgs.c.seq), 0) + 1,
            literal(task_id),
            literal(invocation_id),
            literal(role),
            literal(sender, Text),
            literal(content),
            literal([dict(tc) for tc in tool_calls] if tool_calls else None, Json()),
            literal(tool_call_id, Text),
            literal(utcnow(), UtcTimestamp()),
        ).where(_msgs.c.user_id == user_id, _msgs.c.agent == agent)
        row = await write_returning(self._db, _msgs.insert().from_select(_APPEND_COLUMNS, values).returning(_msgs))
        assert row is not None
        return row

    async def stack_history(self, user_id: str, agent: str) -> list[Row]:
        """Uncompacted stack messages in `seq` order (the history a turn starts with)."""
        return await fetch_all(
            self._db,
            select(_msgs)
            .where(_msgs.c.user_id == user_id, _msgs.c.agent == agent, _msgs.c.compacted.is_(False))
            .order_by(_msgs.c.seq),
        )

    async def compaction_candidates(self, user_id: str, agent: str, current_task_id: str) -> list[Row]:
        """Uncompacted messages of finished tasks other than the current one, in `seq` order."""
        return await fetch_all(
            self._db,
            select(_msgs)
            .join(_tasks, _tasks.c.id == _msgs.c.task_id)
            .where(
                _msgs.c.user_id == user_id,
                _msgs.c.agent == agent,
                _msgs.c.compacted.is_(False),
                _msgs.c.task_id != current_task_id,
                _tasks.c.status != "running",
            )
            .order_by(_msgs.c.seq),
        )

    async def apply_compaction(self, user_id: str, agent: str, summary: str, message_ids: Iterable[int]) -> None:
        """One transaction: upsert the stack summary and flag the summarised messages compacted."""
        insert = upsert(self._db, _summaries).values(user_id=user_id, agent=agent, summary=summary, updated_at=utcnow())
        async with self._db.begin() as conn:
            await conn.execute(
                insert.on_conflict_do_update(
                    index_elements=[_summaries.c.user_id, _summaries.c.agent],
                    set_={"summary": insert.excluded.summary, "updated_at": insert.excluded.updated_at},
                )
            )
            await conn.execute(_msgs.update().where(_msgs.c.id.in_(list(message_ids))).values(compacted=True))

    async def get_summary(self, user_id: str, agent: str) -> str | None:
        row = await fetch_one(
            self._db, select(_summaries.c.summary).where(_summaries.c.user_id == user_id, _summaries.c.agent == agent)
        )
        return row["summary"] if row else None

    async def messages_page(self, user_id: str, agent: str, before_seq: int | None, limit: int) -> list[Row]:
        """The newest `limit` messages with `seq < before_seq` (all when None), in ascending `seq`."""
        newest = select(_msgs).where(_msgs.c.user_id == user_id, _msgs.c.agent == agent)
        if before_seq is not None:
            newest = newest.where(_msgs.c.seq < before_seq)
        page = newest.order_by(_msgs.c.seq.desc()).limit(limit).subquery()
        return await fetch_all(self._db, select(page).order_by(page.c.seq))

    async def invocation_messages(self, invocation_id: str) -> list[Row]:
        return await fetch_all(
            self._db, select(_msgs).where(_msgs.c.invocation_id == invocation_id).order_by(_msgs.c.seq)
        )
