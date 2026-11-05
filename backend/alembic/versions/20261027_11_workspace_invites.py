"""Workspace invites and membership provenance (T-1.1, US-03).

Revision ID: 20261027_11
Revises: 20261026_10
Create Date: 2026-10-27

Existing memberships get status 'active' and no inviter (they pre-date invites).
``workspace_memberships.invited_at`` already plays the role of the spec's
``created_at``, so no new timestamp is added.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261027_11"
down_revision: str | None = "20261026_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

invite_status = postgresql.ENUM(
    "PENDING", "ACCEPTED", "REVOKED", "EXPIRED", name="invite_status", create_type=False
)
workspace_role = postgresql.ENUM(
    "OWNER", "EDITOR", "VIEWER", name="workspace_role", create_type=False
)


def upgrade() -> None:
    op.add_column(
        "workspace_memberships",
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "workspace_memberships",
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
    )
    op.create_foreign_key(
        "fk_membership_invited_by",
        "workspace_memberships",
        "users",
        ["invited_by"],
        ["id"],
        ondelete="SET NULL",
    )

    invite_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "workspace_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", workspace_role, nullable=True),
        sa.Column("custom_role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", invite_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["custom_role_id", "workspace_id"],
            ["workspace_roles.id", "workspace_roles.workspace_id"],
            name="fk_invite_custom_role",
        ),
        sa.CheckConstraint(
            "(role IS NULL) <> (custom_role_id IS NULL)",
            name="ck_invite_exactly_one_role",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invites_token_hash"),
    )
    op.create_index("ix_workspace_invites_workspace_id", "workspace_invites", ["workspace_id"])
    op.create_index(
        "uq_workspace_invites_pending",
        "workspace_invites",
        ["workspace_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_invites_pending", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_workspace_id", table_name="workspace_invites")
    op.drop_table("workspace_invites")
    invite_status.drop(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        "fk_membership_invited_by", "workspace_memberships", type_="foreignkey"
    )
    op.drop_column("workspace_memberships", "status")
    op.drop_column("workspace_memberships", "invited_by")
