"""Custom per-workspace roles with user-defined permissions (T-21.1).

Revision ID: 20261018_09
Revises: 20261008_08
Create Date: 2026-10-18

Existing memberships keep their built-in OWNER/EDITOR/VIEWER role untouched, so
no backfill is needed: every workspace creator is already an OWNER. Built-in roles
are not rows in ``workspace_roles``; only custom roles are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261018_09"
down_revision: str | None = "20261008_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_roles_workspace_id", "workspace_roles", ["workspace_id"])
    op.create_index(
        "uq_workspace_roles_name",
        "workspace_roles",
        ["workspace_id", sa.text("lower(name)")],
        unique=True,
    )

    op.add_column(
        "workspace_memberships",
        sa.Column("custom_role_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_membership_custom_role",
        "workspace_memberships",
        "workspace_roles",
        ["custom_role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_workspace_memberships_custom_role_id",
        "workspace_memberships",
        ["custom_role_id"],
    )
    op.alter_column("workspace_memberships", "role", nullable=True)
    op.create_check_constraint(
        "ck_membership_exactly_one_role",
        "workspace_memberships",
        "(role IS NULL) <> (custom_role_id IS NULL)",
    )


def downgrade() -> None:
    # Custom-role members have no built-in role to fall back to; make them VIEWERs,
    # the least privilege, rather than failing the downgrade.
    op.drop_constraint(
        "ck_membership_exactly_one_role", "workspace_memberships", type_="check"
    )
    op.execute(
        "UPDATE workspace_memberships SET role = 'VIEWER' WHERE role IS NULL"
    )
    op.alter_column("workspace_memberships", "role", nullable=False)
    op.drop_index(
        "ix_workspace_memberships_custom_role_id", table_name="workspace_memberships"
    )
    op.drop_constraint(
        "fk_membership_custom_role", "workspace_memberships", type_="foreignkey"
    )
    op.drop_column("workspace_memberships", "custom_role_id")
    op.drop_index("uq_workspace_roles_name", table_name="workspace_roles")
    op.drop_index("ix_workspace_roles_workspace_id", table_name="workspace_roles")
    op.drop_table("workspace_roles")
