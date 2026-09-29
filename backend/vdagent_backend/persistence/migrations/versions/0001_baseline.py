"""Baseline: the schema of the pre-Alembic `schema.sql`.

Databases created before Alembic already have exactly this schema; `migrate()` stamps them at
this revision instead of running it.

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vdagent_backend.persistence.types import Embedding, Json, UtcTimestamp

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[str]:
    return sa.Column("created_at", UtcTimestamp(), nullable=False)


def _flag(name: str) -> sa.Column[bool]:
    return sa.Column(name, sa.Boolean(create_constraint=True), nullable=False, server_default=sa.false())


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        _created_at(),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("root_agent", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _created_at(),
        sa.Column("finished_at", UtcTimestamp()),
        sa.CheckConstraint("status IN ('running','completed','failed','cancelled')"),
    )
    op.create_index("ix_tasks_user", "tasks", ["user_id", "created_at"])
    op.create_table(
        "invocations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("caller", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), sa.ForeignKey("invocations.id")),
        sa.Column("tool_call_id", sa.Text()),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("inbound_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result_text", sa.Text()),
        sa.Column("error", sa.Text()),
        _created_at(),
        sa.Column("started_at", UtcTimestamp()),
        sa.Column("finished_at", UtcTimestamp()),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled','rejected')"),
    )
    op.create_index("ix_inv_task", "invocations", ["task_id"])
    op.create_index("ix_inv_stack", "invocations", ["user_id", "agent", "status"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("invocation_id", sa.Text(), sa.ForeignKey("invocations.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("sender", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls_json", Json()),
        sa.Column("tool_call_id", sa.Text()),
        _flag("compacted"),
        _created_at(),
        sa.CheckConstraint("role IN ('user','assistant','tool')"),
        sa.UniqueConstraint("user_id", "agent", "seq"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_msg_task", "messages", ["task_id"])
    op.create_table(
        "stack_summaries",
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("updated_at", UtcTimestamp(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "agent"),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invocation_id", sa.Text(), sa.ForeignKey("invocations.id"), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("source_sql", sa.Text(), nullable=False),
        sa.Column("columns_json", Json(), nullable=False),
        sa.Column("rows_json", Json(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        _flag("truncated"),
        _created_at(),
    )
    op.create_index("ix_ds_user", "datasets", ["user_id"])
    op.create_table(
        "charts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invocation_id", sa.Text(), sa.ForeignKey("invocations.id"), nullable=False),
        sa.Column("dataset_id", sa.Text(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("spec_json", Json(), nullable=False),
        _created_at(),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invocation_id", sa.Text(), sa.ForeignKey("invocations.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        _created_at(),
    )
    op.create_index("ix_rp_user", "reports", ["user_id", "created_at"])
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Embedding()),
        _created_at(),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_memories_scope", "memories", ["user_id", "agent", "id"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute("CREATE VIRTUAL TABLE memories_fts USING fts5(text, content='memories', content_rowid='id')")
        op.execute(
            "CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN "
            "INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END"
        )
        op.execute(
            "CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN "
            "INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text); END"
        )


def downgrade() -> None:
    raise NotImplementedError("the baseline cannot be downgraded")
