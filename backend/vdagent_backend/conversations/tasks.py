"""The `tasks` and `invocations` tables.

A task is one human message and everything it caused; an invocation is one agent turn inside it
(the root invocation answers the human, the others answer `send_to_agent` calls). Status moves are
guarded in SQL, so a row that already reached a terminal status is never overwritten.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from vdagent_backend.core import new_id, utcnow
from vdagent_backend.persistence import Row, fetch_all, fetch_one, tables, write_returning, write_returning_all

TASK_STATUSES = ("running", "completed", "failed", "cancelled")
TERMINAL_INVOCATION = ("completed", "failed", "cancelled", "rejected")
_INFLIGHT = ("queued", "running")

_tasks = tables.tasks
_invs = tables.invocations


class Tasks:
    """Repository of tasks and their invocations."""

    def __init__(self, db: AsyncEngine) -> None:
        self._db = db

    # ------------------------------------------------------------------ tasks

    async def create_task(
        self, user_id: str, root_agent: str, inbound_text: str, idempotency_key: str | None = None
    ) -> tuple[Row, Row]:
        """A running task and its queued root invocation, in one transaction.

        Raises:
            IntegrityError: `idempotency_key` is already used by this user with this agent (a concurrent retry won).
        """
        now = utcnow()
        task_id = new_id("t")
        async with self._db.begin() as conn:
            task = await conn.execute(
                _tasks.insert()
                .values(id=task_id, user_id=user_id, root_agent=root_agent, status="running", created_at=now,
                        idempotency_key=idempotency_key)
                .returning(_tasks)
            )
            task_row = dict(task.mappings().one())
            inv = await conn.execute(
                _invs.insert()
                .values(
                    id=new_id("inv"),
                    task_id=task_id,
                    user_id=user_id,
                    agent=root_agent,
                    caller="user",
                    depth=0,
                    inbound_text=inbound_text,
                    status="queued",
                    created_at=now,
                )
                .returning(_invs)
            )
            return task_row, dict(inv.mappings().one())

    async def find_keyed_task(self, user_id: str, root_agent: str, idempotency_key: str) -> tuple[Row, Row] | None:
        """The task (and its root invocation) this user started with `idempotency_key` on `root_agent` (WS7 F-11)."""
        task = await fetch_one(
            self._db,
            select(_tasks).where(
                _tasks.c.user_id == user_id, _tasks.c.root_agent == root_agent, _tasks.c.idempotency_key == idempotency_key
            ),
        )
        if task is None:
            return None
        root = await fetch_one(
            self._db, select(_invs).where(_invs.c.task_id == task["id"], _invs.c.depth == 0).order_by(_invs.c.created_at)
        )
        assert root is not None
        return task, root

    async def get_task(self, task_id: str, user_id: str | None = None) -> Row | None:
        """A task by id; with `user_id`, only if owned by that user."""
        stmt = select(_tasks).where(_tasks.c.id == task_id)
        if user_id is not None:
            stmt = stmt.where(_tasks.c.user_id == user_id)
        return await fetch_one(self._db, stmt)

    async def list_tasks(self, user_id: str, status: str | None = None, limit: int = 50) -> list[Row]:
        """The user's tasks, newest first."""
        stmt = select(_tasks).where(_tasks.c.user_id == user_id)
        if status is not None:
            stmt = stmt.where(_tasks.c.status == status)
        stmt = stmt.order_by(_tasks.c.created_at.desc(), _tasks.c.id.desc()).limit(limit)
        return await fetch_all(self._db, stmt)

    async def finish_task(self, task_id: str, status: str, outcome: str | None = None) -> Row | None:
        """Move a running task to a terminal status (with the run's `outcome`, WS7 F-03); the updated row, or None if it
        was not running."""
        return await write_returning(
            self._db,
            _tasks.update()
            .where(_tasks.c.id == task_id, _tasks.c.status == "running")
            .values(status=status, outcome=outcome, finished_at=utcnow())
            .returning(_tasks),
        )

    async def fail_running_tasks(self) -> list[Row]:
        """Startup recovery: every running task → failed, outcome `interrupted` (WS7 F-04)."""
        return await write_returning_all(
            self._db,
            _tasks.update()
            .where(_tasks.c.status == "running")
            .values(status="failed", outcome="interrupted", finished_at=utcnow())
            .returning(_tasks),
        )

    # ------------------------------------------------------------------ invocations

    async def insert_invocation(
        self,
        *,
        id: str,
        task_id: str,
        user_id: str,
        agent: str,
        caller: str,
        parent_id: str | None,
        tool_call_id: str | None,
        depth: int,
        inbound_text: str,
        status: str,
        error: str | None = None,
    ) -> Row:
        """A child invocation: `queued` when accepted, or already terminal (`rejected`)."""
        now = utcnow()
        row = await write_returning(
            self._db,
            _invs.insert()
            .values(
                id=id,
                task_id=task_id,
                user_id=user_id,
                agent=agent,
                caller=caller,
                parent_id=parent_id,
                tool_call_id=tool_call_id,
                depth=depth,
                inbound_text=inbound_text,
                status=status,
                error=error,
                created_at=now,
                finished_at=now if status in TERMINAL_INVOCATION else None,
            )
            .returning(_invs),
        )
        assert row is not None
        return row

    async def mark_invocation_running(self, invocation_id: str) -> Row:
        row = await write_returning(
            self._db,
            _invs.update().where(_invs.c.id == invocation_id).values(status="running", started_at=utcnow()).returning(_invs),
        )
        assert row is not None
        return row

    async def finish_invocation(
        self, invocation_id: str, status: str, *, result_text: str | None = None, error: str | None = None
    ) -> Row | None:
        """Move a queued/running invocation to a terminal status; None if it was already terminal."""
        return await write_returning(
            self._db,
            _invs.update()
            .where(_invs.c.id == invocation_id, _invs.c.status.in_(_INFLIGHT))
            .values(status=status, result_text=result_text, error=error, finished_at=utcnow())
            .returning(_invs),
        )

    async def cancel_task_invocations(self, task_id: str) -> list[Row]:
        """Every queued/running invocation of the task → `cancelled`; returns the changed rows."""
        return await write_returning_all(
            self._db,
            _invs.update()
            .where(_invs.c.task_id == task_id, _invs.c.status.in_(_INFLIGHT))
            .values(status="cancelled", finished_at=utcnow())
            .returning(_invs),
        )

    async def list_task_invocations(self, task_id: str) -> list[Row]:
        return await fetch_all(
            self._db, select(_invs).where(_invs.c.task_id == task_id).order_by(_invs.c.created_at, _invs.c.id)
        )

    async def inflight_invocations(self) -> list[Row]:
        """Every queued/running invocation of every user (startup recovery)."""
        return await fetch_all(
            self._db, select(_invs).where(_invs.c.status.in_(_INFLIGHT)).order_by(_invs.c.created_at, _invs.c.id)
        )
