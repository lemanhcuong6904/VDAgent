"""Every Backend table, declared once on `metadata` (the schema at the Alembic head).

Column names, nullability, checks, keys and indexes are those of the database; JSON columns keep
their `*_json` names and decode through `Json`. Timestamps default to `core.utcnow()` in Python.
The memory full-text index (`memories_fts` and its triggers) is SQLite-only and lives in the
migrations, not here. Change a table here and in a new Alembic revision together.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    false,
)

from vdagent_backend.core import utcnow
from vdagent_backend.persistence.types import Embedding, Json, UtcTimestamp

metadata = MetaData()


def _created_at() -> Column[str]:
    return Column("created_at", UtcTimestamp, nullable=False, default=utcnow)


users = Table(
    "users",
    metadata,
    Column("id", Text, primary_key=True),  # u_…
    Column("name", Text, nullable=False),
    _created_at(),
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", Text, primary_key=True),  # t_…
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("root_agent", Text, nullable=False),  # the agent whose chat the human posted in
    Column("status", Text, nullable=False),
    _created_at(),
    Column("finished_at", UtcTimestamp),
    Column("outcome", Text),  # completed | partial | failed | interrupted (NULL: not reported) — WS7 F-03/F-04
    Column("idempotency_key", Text),  # client Idempotency-Key of the triggering message — WS7 F-11
    CheckConstraint("status IN ('running','completed','failed','cancelled')"),
    Index("ix_tasks_user", "user_id", "created_at"),
)
# One task per (user, agent, key): a retried request returns the first task instead of running again.
Index(
    "ux_tasks_idempotency",
    tasks.c.user_id,
    tasks.c.root_agent,
    tasks.c.idempotency_key,
    unique=True,
    sqlite_where=tasks.c.idempotency_key.isnot(None),
)

invocations = Table(
    "invocations",
    metadata,
    Column("id", Text, primary_key=True),  # inv_…
    Column("task_id", Text, ForeignKey("tasks.id"), nullable=False),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("agent", Text, nullable=False),  # callee = stack owner
    Column("caller", Text, nullable=False),  # 'user' or an agent name
    Column("parent_id", Text, ForeignKey("invocations.id")),
    Column("tool_call_id", Text),  # the parent's send_to_agent tool call id
    Column("depth", Integer, nullable=False),
    Column("inbound_text", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("result_text", Text),
    Column("error", Text),
    _created_at(),
    Column("started_at", UtcTimestamp),
    Column("finished_at", UtcTimestamp),
    CheckConstraint("status IN ('queued','running','completed','failed','cancelled','rejected')"),
    Index("ix_inv_task", "task_id"),
    Index("ix_inv_stack", "user_id", "agent", "status"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("agent", Text, nullable=False),  # stack = (user_id, agent)
    Column("seq", Integer, nullable=False),  # per-stack order, starts at 1
    Column("task_id", Text, ForeignKey("tasks.id"), nullable=False),
    Column("invocation_id", Text, ForeignKey("invocations.id"), nullable=False),
    Column("role", Text, nullable=False),
    Column("sender", Text),  # role=user: 'user' or the calling agent
    Column("content", Text, nullable=False, server_default=""),  # raw text, no [from:] prefix
    Column("tool_calls_json", Json),  # role=assistant: [{"id", "name", "arguments_json"}]
    Column("tool_call_id", Text),  # role=tool
    Column("compacted", Boolean(create_constraint=True), nullable=False, server_default=false(), default=False),
    _created_at(),
    CheckConstraint("role IN ('user','assistant','tool')"),
    UniqueConstraint("user_id", "agent", "seq"),
    Index("ix_msg_task", "task_id"),
    sqlite_autoincrement=True,
)

stack_summaries = Table(
    "stack_summaries",
    metadata,
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("agent", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("updated_at", UtcTimestamp, nullable=False, default=utcnow),
    PrimaryKeyConstraint("user_id", "agent"),
)

datasets = Table(
    "datasets",
    metadata,
    Column("id", Text, primary_key=True),  # ds_…; also its table name in query_datasets
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("invocation_id", Text, ForeignKey("invocations.id"), nullable=False),
    Column("name", Text),
    Column("source_sql", Text, nullable=False),
    Column("columns_json", Json, nullable=False),  # [{"name", "type"}]
    Column("row_count", Integer, nullable=False),
    Column("truncated", Boolean(create_constraint=True), nullable=False, server_default=false(), default=False),
    _created_at(),
    Index("ix_ds_user", "user_id"),
)

# One row per dataset row (at most 10 000 per dataset), so a page reads only its rows.
dataset_rows = Table(
    "dataset_rows",
    metadata,
    Column("dataset_id", Text, ForeignKey("datasets.id"), nullable=False),
    Column("idx", Integer, nullable=False),  # 0-based position in the query result
    Column("row", Json, nullable=False),  # the row's values in column order
    PrimaryKeyConstraint("dataset_id", "idx"),
)

charts = Table(
    "charts",
    metadata,
    Column("id", Text, primary_key=True),  # ch_…
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("invocation_id", Text, ForeignKey("invocations.id"), nullable=False),
    Column("dataset_id", Text, ForeignKey("datasets.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("spec_json", Json, nullable=False),  # Vega-Lite v6, data inlined
    _created_at(),
)

reports = Table(
    "reports",
    metadata,
    Column("id", Text, primary_key=True),  # rp_…
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("invocation_id", Text, ForeignKey("invocations.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("markdown", Text, nullable=False),
    _created_at(),
    Index("ix_rp_user", "user_id", "created_at"),
)

# Agent memory: notes of one (user_id, agent) scope. Embeddings are the plugin's own (any model,
# any dimension; NULL = none).
memories = Table(
    "memories",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("agent", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("embedding", Embedding),
    _created_at(),
    Index("ix_memories_scope", "user_id", "agent", "id"),
    sqlite_autoincrement=True,
)

# Artifact envelopes (D5): immutable, versioned, content-hashed; owned by one user. A correction is a new version of
# the same artifact_id and the previous version's status becomes SUPERSEDED — the only update the SQLite triggers
# (in the migrations, like the memory index) allow; deletes are refused.
artifacts = Table(
    "artifacts",
    metadata,
    Column("artifact_id", Text, nullable=False),  # art_…
    Column("version", Integer, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("task_id", Text, nullable=False),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("artifact_type", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("producer_json", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("snapshot_refs_json", Text, nullable=False),
    Column("semantic_config_version", Text),
    Column("source_refs_json", Text, nullable=False),
    Column("input_refs_json", Text, nullable=False),
    Column("evidence_refs_json", Text, nullable=False),
    Column("limitations_json", Text, nullable=False),
    Column("reason_code", Text),
    Column("reason", Text),
    Column("payload_json", Text, nullable=False),  # canonical JSON, Decimal as string
    Column("created_at", Text, nullable=False),
    PrimaryKeyConstraint("artifact_id", "version"),
    CheckConstraint("version >= 1"),
    CheckConstraint("status IN ('DRAFT','VALID','PARTIAL','INVALID','SUPERSEDED')"),
    Index("ix_artifacts_run", "user_id", "run_id", "artifact_type"),
)

# Authorized scope per user (D8): a whole project (zone_id NULL) or one zone of it; unique per
# (user, project, zone) through an expression index in the migrations.
user_scopes = Table(
    "user_scopes",
    metadata,
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("project_id", Text, nullable=False),
    Column("zone_id", Text),
)
