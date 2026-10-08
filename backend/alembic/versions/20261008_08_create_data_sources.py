"""Record each workspace's connected data sources and their sync state (T-10.1).

Revision ID: 20261008_08
Revises: 20261004_07
Create Date: 2026-10-08

No backfill. A repository ingested before this migration has graph nodes but no
row here; `GET /api/workspaces/{id}/sources` reports those as SUCCESS with
unknown timestamps rather than hiding them (see app/api/graph.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_08"
down_revision: str | None = "20261004_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

sync_status = postgresql.ENUM(
    "PENDING", "SUCCESS", "FAILED", name="data_source_sync_status", create_type=False
)


def upgrade() -> None:
    sync_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=512), nullable=False),
        sa.Column("status", sync_status, nullable=False),
        # Separate columns on purpose: a source that succeeded on Monday and
        # failed today must show both the failure and the real age of its data.
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        # SET NULL: losing a member must not erase a source's sync history.
        sa.ForeignKeyConstraint(["last_synced_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "kind", "external_ref", name="uq_data_source_workspace_ref"
        ),
    )
    op.create_index("ix_data_sources_workspace_id", "data_sources", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_data_sources_workspace_id", table_name="data_sources")
    op.drop_table("data_sources")
    sync_status.drop(op.get_bind(), checkfirst=True)
