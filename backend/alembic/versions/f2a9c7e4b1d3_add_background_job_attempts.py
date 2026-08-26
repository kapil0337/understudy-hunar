"""add background_job attempts

Revision ID: f2a9c7e4b1d3
Revises: c160445ffa1b
Create Date: 2026-08-26 08:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a9c7e4b1d3"
down_revision: str | None = "c160445ffa1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "background_job",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("background_job", "attempts")
