"""Comments on graph nodes and edges, and per-reader read markers (T-27.1).

Revision ID: 20261105_15
Revises: 20261105_14
Create Date: 2026-11-05

No foreign key to the thing a comment is about: graph nodes live in Neo4j. The
comment carries the client's key for its target instead -- the same string the
canvas and inspector already address it by.

``graph_comments.author_id`` is ON DELETE SET NULL, not CASCADE. Removing a
member must not rewrite a discussion other people took decisions from, so the
comment survives unattributed. ``graph_comment_views.user_id`` *is* CASCADE: a
read marker is private bookkeeping and means nothing once its owner is gone.

Both tables cascade from ``workspaces``, which is what US-05's workspace delete
relies on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261105_15"
down_revision: str | None = "20261105_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_kind", sa.String(length=8), nullable=False),
        sa.Column("target_key", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "target_kind IN ('node', 'edge')", name="ck_graph_comments_target_kind"
        ),
    )
    op.create_index(
        "ix_graph_comments_workspace_id", "graph_comments", ["workspace_id"]
    )
    op.create_index("ix_graph_comments_author_id", "graph_comments", ["author_id"])
    # Covers the inspector's read: one target's thread, oldest first.
    op.create_index(
        "ix_graph_comments_target",
        "graph_comments",
        ["workspace_id", "target_kind", "target_key", "created_at"],
    )

    op.create_table(
        "graph_comment_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_kind", sa.String(length=8), nullable=False),
        sa.Column("target_key", sa.String(length=512), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            "target_kind",
            "target_key",
            name="uq_graph_comment_view_target",
        ),
        sa.CheckConstraint(
            "target_kind IN ('node', 'edge')",
            name="ck_graph_comment_views_target_kind",
        ),
    )
    op.create_index(
        "ix_graph_comment_views_workspace_id", "graph_comment_views", ["workspace_id"]
    )
    op.create_index(
        "ix_graph_comment_views_user_id", "graph_comment_views", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_graph_comment_views_user_id", table_name="graph_comment_views")
    op.drop_index(
        "ix_graph_comment_views_workspace_id", table_name="graph_comment_views"
    )
    op.drop_table("graph_comment_views")
    op.drop_index("ix_graph_comments_target", table_name="graph_comments")
    op.drop_index("ix_graph_comments_author_id", table_name="graph_comments")
    op.drop_index("ix_graph_comments_workspace_id", table_name="graph_comments")
    op.drop_table("graph_comments")
