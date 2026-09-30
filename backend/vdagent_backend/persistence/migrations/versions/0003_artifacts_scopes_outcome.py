"""Staging-agent integration: artifact envelopes, user scopes, task outcome and idempotency key.

Databases created by staging-agent's `schema.sql` already have all of this; they are stamped `0001` by `migrate()`,
so every step here checks what exists and adds only what is missing (their data is kept).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS artifacts_immutable_update BEFORE UPDATE ON artifacts
WHEN NOT (NEW.status = 'SUPERSEDED' AND OLD.status <> 'SUPERSEDED'
          AND NEW.payload_json IS OLD.payload_json AND NEW.content_hash IS OLD.content_hash
          AND NEW.artifact_id IS OLD.artifact_id AND NEW.version IS OLD.version)
BEGIN
  SELECT RAISE(ABORT, 'artifacts are immutable');
END""",
    """CREATE TRIGGER IF NOT EXISTS artifacts_immutable_delete BEFORE DELETE ON artifacts
BEGIN
  SELECT RAISE(ABORT, 'artifacts are immutable');
END""",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    task_columns = {c["name"] for c in inspector.get_columns("tasks")}
    # plain ADD COLUMN (no table recreate): the unnamed status CHECK of `tasks` stays in place
    if "outcome" not in task_columns:
        op.add_column("tasks", sa.Column("outcome", sa.Text()))
    if "idempotency_key" not in task_columns:
        op.add_column("tasks", sa.Column("idempotency_key", sa.Text()))
    if "ux_tasks_idempotency" not in {i["name"] for i in inspector.get_indexes("tasks")}:
        op.create_index(
            "ux_tasks_idempotency", "tasks", ["user_id", "root_agent", "idempotency_key"], unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        )
    if "artifacts" not in tables:
        op.create_table(
            "artifacts",
            sa.Column("artifact_id", sa.Text(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("task_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("artifact_type", sa.Text(), nullable=False),
            sa.Column("schema_version", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("producer_json", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.Text(), nullable=False),
            sa.Column("snapshot_refs_json", sa.Text(), nullable=False),
            sa.Column("semantic_config_version", sa.Text()),
            sa.Column("source_refs_json", sa.Text(), nullable=False),
            sa.Column("input_refs_json", sa.Text(), nullable=False),
            sa.Column("evidence_refs_json", sa.Text(), nullable=False),
            sa.Column("limitations_json", sa.Text(), nullable=False),
            sa.Column("reason_code", sa.Text()),
            sa.Column("reason", sa.Text()),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("artifact_id", "version"),
            sa.CheckConstraint("version >= 1"),
            sa.CheckConstraint("status IN ('DRAFT','VALID','PARTIAL','INVALID','SUPERSEDED')"),
        )
        op.create_index("ix_artifacts_run", "artifacts", ["user_id", "run_id", "artifact_type"])
    if "user_scopes" not in tables:
        op.create_table(
            "user_scopes",
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("project_id", sa.Text(), nullable=False),
            sa.Column("zone_id", sa.Text()),
        )
    if bind.dialect.name == "sqlite":
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_user_scopes ON user_scopes(user_id, project_id, IFNULL(zone_id, ''))")
        for trigger in _SQLITE_TRIGGERS:
            op.execute(trigger)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS artifacts_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS artifacts_immutable_delete")
        op.execute("DROP INDEX IF EXISTS ux_user_scopes")
    op.drop_table("user_scopes")
    op.drop_index("ix_artifacts_run", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ux_tasks_idempotency", table_name="tasks")
    op.drop_column("tasks", "idempotency_key")  # native DROP COLUMN (SQLite 3.35+), keeps the status CHECK
    op.drop_column("tasks", "outcome")
