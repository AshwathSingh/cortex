"""Workspace-scoped chat provider credentials and in-flight installs (T-8.2).

Revision ID: 20261031_11
Revises: 20261026_10
Create Date: 2026-10-31

Additive: two new tables, nothing existing is touched, so there is no backfill.
``access_token`` is nullable because Discord's bot token is one application-wide
secret in config rather than a per-workspace one -- see the column comment in
``app.models.source_credential``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031_11"
down_revision: str | None = "20261026_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=512), nullable=False),
        sa.Column("installed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["installed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "kind", name="uq_source_credential_kind"
        ),
    )
    op.create_index(
        "ix_source_credentials_workspace_id", "source_credentials", ["workspace_id"]
    )

    op.create_table(
        "source_install_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_source_install_transactions_expires_at",
        "source_install_transactions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_install_transactions_expires_at",
        table_name="source_install_transactions",
    )
    op.drop_table("source_install_transactions")
    op.drop_index(
        "ix_source_credentials_workspace_id", table_name="source_credentials"
    )
    op.drop_table("source_credentials")
