"""T-10.1: one row per data source connected to a workspace, with its sync state.

US-7's ingestion is all-or-nothing -- every failure path raises before
``write_graph``, and ``write_graph`` writes everything or nothing -- so a failed
ingestion leaves *zero* Neo4j nodes. Without this table a repository that was
connected and failed is indistinguishable from one nobody ever connected, and
there is nowhere a sync timestamp could live. US-7's README listed the table as
deliberately deferred to US-10; this is it.

The graph stays authoritative for *contents* (how many pull requests and issues
are indexed). This table is authoritative for *which sources exist* and what
happened the last time Cortex tried to read them.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
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

# The only ``kind`` that exists. A plain string rather than an enum: the next
# source type should not need a migration to add a value, and nothing branches
# on it except the graph-count lookup, which is GitHub-specific anyway.
GITHUB_KIND = "github"


class SyncStatus(str, enum.Enum):
    """PENDING is written before the fetch starts, so a synchronous ingestion
    that is still running (or died mid-request) is visible as "Syncing…" rather
    than as nothing at all."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        # Connecting the same repo twice to one workspace re-syncs it rather
        # than creating a second row; two workspaces keep separate rows, the
        # same way they keep separate graph nodes.
        UniqueConstraint(
            "workspace_id", "kind", "external_ref", name="uq_data_source_workspace_ref"
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
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: ``owner/repo`` for ``kind="github"``.
    external_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="data_source_sync_status"), nullable=False
    )

    # Deliberately two columns, not one. A source that succeeded on Monday and
    # failed today has to show both "Needs attention" *and* "Synced 3 days ago",
    # because the data on screen really is three days old. Collapsing them would
    # force the UI to either hide the failure or misstate the freshness.
    #
    # ``last_attempted_at`` is NOT NULL because a row only ever comes into
    # existence as part of an attempt; ``last_synced_at`` stays NULL until an
    # attempt actually succeeds.
    last_attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The user-facing detail of the last failure; cleared by a success.
    last_error: Mapped[str | None] = mapped_column(Text)
    # Who last refreshed it. The workspace is shared, so "Synced 5 min ago by
    # Ashwath" answers the question the timestamp alone raises. SET NULL rather
    # than CASCADE: losing a member must not erase the source's sync history.
    last_synced_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="data_sources")
    synced_by: Mapped["User | None"] = relationship()
