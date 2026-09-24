"""Add an optional description to workspaces (US-2).

Revision ID: 20260924_05
Revises: 20260924_04
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_05"
down_revision: str | None = "20260924_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "description")
