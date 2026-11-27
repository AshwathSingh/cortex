"""Indexed removed targets and a constant-size workspace write fence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261126_17"
down_revision = "20261117_16"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workspaces",
        sa.Column(
            "source_removal_revision",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "source_removals_pending", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_workspace_pending_removals", "workspaces", "source_removals_pending >= 0"
    )
    op.create_table(
        "source_removal_targets",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_removal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_removals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("target_key", sa.String(512), primary_key=True),
    )
    op.create_index(
        "ix_removal_target_workspace_key",
        "source_removal_targets",
        ["workspace_id", "target_key"],
    )
    # Preserve both completed tombstones and pending retry plans from revision 16.
    op.execute("""INSERT INTO source_removal_targets (workspace_id, source_removal_id, target_key)
        SELECT r.workspace_id, r.id, k.key FROM source_removals r
        CROSS JOIN LATERAL json_array_elements_text(COALESCE(r.targets->'keys', '[]'::json)) AS k(key)
        ON CONFLICT DO NOTHING""")
    op.execute("""UPDATE workspaces w SET source_removal_revision = s.total,
        source_removals_pending = s.pending FROM (
        SELECT workspace_id, count(*) AS total, count(*) FILTER (WHERE pending) AS pending
        FROM source_removals GROUP BY workspace_id) s WHERE w.id = s.workspace_id""")
    op.execute("UPDATE source_removals SET targets = '{}'::json WHERE NOT pending")


def downgrade():
    op.execute("""UPDATE source_removals r SET targets = json_build_object('keys', s.keys)
        FROM (SELECT source_removal_id, json_agg(target_key) AS keys
        FROM source_removal_targets GROUP BY source_removal_id) s
        WHERE r.id = s.source_removal_id AND NOT r.pending""")
    op.drop_table("source_removal_targets")
    op.drop_constraint("ck_workspace_pending_removals", "workspaces", type_="check")
    op.drop_column("workspaces", "source_removals_pending")
    op.drop_column("workspaces", "source_removal_revision")
