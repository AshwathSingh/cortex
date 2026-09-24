"""Use workspace memberships as the single ownership source.

Revision ID: 20260924_04
Revises: 20260923_03
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260924_04"
down_revision: str | None = "20260923_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_column("workspaces", "owner_id")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE workspaces
        SET owner_id = owners.user_id
        FROM (
            SELECT DISTINCT ON (workspace_id) workspace_id, user_id
            FROM workspace_memberships
            WHERE role = 'OWNER'
            ORDER BY workspace_id, invited_at
        ) AS owners
        WHERE workspaces.id = owners.workspace_id
        """
    )
    op.alter_column("workspaces", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_workspaces_owner_id_users",
        "workspaces",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
