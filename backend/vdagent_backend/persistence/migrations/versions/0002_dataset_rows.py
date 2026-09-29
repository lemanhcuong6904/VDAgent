"""Store dataset rows one per row in `dataset_rows` instead of one `datasets.rows_json` array.

Every existing dataset's rows are copied in array order (`idx` = array index), then
`datasets.rows_json` is dropped (native `ALTER TABLE … DROP COLUMN`, SQLite 3.35+). Not reversible.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vdagent_backend.persistence.types import Json

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_rows",
        sa.Column("dataset_id", sa.Text(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("row", Json(), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", "idx"),
    )
    # Only SQLite databases predate this revision; on any other dialect `datasets` is empty here.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            'INSERT INTO dataset_rows (dataset_id, idx, "row") '
            "SELECT d.id, CAST(j.key AS INTEGER), j.value FROM datasets d, json_each(d.rows_json) j"
        )
    op.drop_column("datasets", "rows_json")


def downgrade() -> None:
    raise NotImplementedError("0002_dataset_rows is not reversible")
