"""Workspace lifecycle status, for cascading delete (T-5.1).

Revision ID: 20261103_13
Revises: 20261029_12
Create Date: 2026-11-03

``active`` (every existing workspace) or ``deleting``. Deleting a workspace spans
Postgres and Neo4j, which cannot share a transaction, so it is marked first and
hidden from every endpoint while the two stores are cleared.

Every foreign key to ``workspaces`` is already ON DELETE CASCADE (memberships,
data sources, custom roles, invites), so no key changes are needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_13"
down_revision: str | None = "20261029_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
    )
    op.create_check_constraint(
        "ck_workspaces_status", "workspaces", "status IN ('active', 'deleting')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspaces_status", "workspaces", type_="check")
    op.drop_column("workspaces", "status")
