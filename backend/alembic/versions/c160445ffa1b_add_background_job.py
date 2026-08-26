"""add background_job

Revision ID: c160445ffa1b
Revises: 86abffcc0b45
Create Date: 2026-08-25 20:55:44.379059

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel.sql.sqltypes import AutoString

from alembic import op

revision: str = "c160445ffa1b"
down_revision: str | None = "86abffcc0b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", AutoString(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", AutoString(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Supports the worker's claim query: WHERE status = 'PENDING' ORDER BY created_at.
    op.create_index(
        "ix_background_job_status_created_at", "background_job", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_background_job_status_created_at", table_name="background_job")
    op.drop_table("background_job")
