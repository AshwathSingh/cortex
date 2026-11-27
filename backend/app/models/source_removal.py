"""Durable cleanup journal and generation fence for source ingestion."""

import uuid
from sqlalchemy import Boolean, ForeignKey, JSON, String, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SourceRemoval(Base):
    __tablename__ = "source_removals"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "kind", "external_ref", name="uq_source_removal_ref"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    external_ref: Mapped[str] = mapped_column(String(512))
    revision: Mapped[str] = mapped_column(String(36))
    pending: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_id: Mapped[str | None] = mapped_column(String(512))
    targets: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceRemovalTarget(Base):
    """Indexed identifiers only: no deleted source content or evidence."""

    __tablename__ = "source_removal_targets"
    __table_args__ = (
        Index("ix_removal_target_workspace_key", "workspace_id", "target_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_removal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_removals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_key: Mapped[str] = mapped_column(String(512), primary_key=True)
