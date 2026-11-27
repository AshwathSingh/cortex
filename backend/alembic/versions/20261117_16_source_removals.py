"""Source cleanup journal and ingestion fences."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261117_16"
down_revision = "20261105_15"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_removals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("external_ref", sa.String(512), nullable=False),
        sa.Column("revision", sa.String(36), nullable=False),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("channel_id", sa.String(512)),
        sa.Column("targets", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "kind", "external_ref", name="uq_source_removal_ref"
        ),
    )
    op.create_index(
        "ix_source_removals_workspace_id", "source_removals", ["workspace_id"]
    )


def downgrade():
    op.drop_table("source_removals")
