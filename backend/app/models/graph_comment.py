"""T-27.1: comments left on graph nodes and edges, and who has read them.

The graph lives in Neo4j and these live in Postgres, so a comment cannot have a
foreign key to the thing it is about. It carries the *client's* key for that
thing instead -- ``"PullRequest:42"`` for a node, ``"Author:7|AUTHORED|Issue:9"``
for an edge -- which is the same string the canvas and the inspector already use
to address it. That makes the key the contract: see ``app.graph.queries.node_key``
and the ``key`` that ``fetch_edge_details`` returns.

Nothing checks that the target exists, deliberately. Checking would make posting
a comment depend on Neo4j being up, and it would still not keep the comment
valid: a pull request deleted upstream has its node pruned on the next
ingestion (T-12.3), and that must not take the discussion about it with it. A
comment whose target has gone is simply not reachable from the canvas.

Two tables, because they answer two different questions. ``graph_comments`` is
the discussion. ``graph_comment_views`` is one row per reader per target holding
*when* they last looked, which is what makes "this node has comments you have
not seen" a single timestamp comparison instead of a per-comment read receipt.
A graph can carry thousands of comments and the canvas asks about all of them at
once, so the cheap shape is the one that matters.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace

#: Longest a single comment may be. Long enough for a real argument, short
#: enough that the inspector can render a thread without paging.
MAX_COMMENT_LENGTH = 4_000

#: Node keys are ``Label:id`` and edge keys are ``source|TYPE|target``; the
#: longest id Cortex writes is a GitHub integer, so this is generous.
MAX_TARGET_KEY_LENGTH = 512


class CommentTarget(str, enum.Enum):
    """What a comment is attached to."""

    NODE = "node"
    EDGE = "edge"


class GraphComment(Base):
    __tablename__ = "graph_comments"
    __table_args__ = (
        # The inspector's read: one target's thread, oldest first. Covering the
        # sort too, because that order is part of the contract (AC1).
        Index(
            "ix_graph_comments_target",
            "workspace_id",
            "target_kind",
            "target_key",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: ``node`` or ``edge``. Plain text rather than a database enum: the two
    #: kinds are a property of the graph model, which is locked, and a third
    #: would be a code change either way.
    target_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    target_key: Mapped[str] = mapped_column(
        String(MAX_TARGET_KEY_LENGTH), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # SET NULL rather than CASCADE: removing someone from the workspace, or
    # deleting their account, must not silently rewrite a discussion other
    # people took decisions from. The comment survives as unattributed.
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workspace: Mapped["Workspace"] = relationship()
    author: Mapped["User | None"] = relationship()


class GraphCommentView(Base):
    """When one reader last looked at one target's comments."""

    __tablename__ = "graph_comment_views"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_id",
            "target_kind",
            "target_key",
            name="uq_graph_comment_view_target",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CASCADE here, unlike the comment's author: a read marker is private
    # bookkeeping for one person and means nothing once they are gone.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    target_key: Mapped[str] = mapped_column(
        String(MAX_TARGET_KEY_LENGTH), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
