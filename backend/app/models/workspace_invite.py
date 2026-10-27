"""T-1.1: a pending offer to join a workspace, redeemed with a secret token."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.workspace import Role, Workspace, WorkspaceRole


class InviteStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_workspace_invites_token_hash"),
        # Same shape as memberships: the role is built-in or custom, never both, and
        # a custom role must belong to the invite's own workspace.
        ForeignKeyConstraint(
            ["custom_role_id", "workspace_id"],
            ["workspace_roles.id", "workspace_roles.workspace_id"],
            name="fk_invite_custom_role",
        ),
        CheckConstraint(
            "(role IS NULL) <> (custom_role_id IS NULL)",
            name="ck_invite_exactly_one_role",
        ),
        # At most one pending invite per (workspace, email). ``email`` is stored
        # lowercase, so plain equality is case-insensitive.
        Index(
            "uq_workspace_invites_pending",
            "workspace_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
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
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # SHA-256 hex of the token. The raw token is shown once, at creation, and is
    # never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Role granted on accept: built-in, or a custom role of this workspace. Defaults
    # to EDITOR at creation (app.services.invites).
    role: Mapped[Role | None] = mapped_column(Enum(Role, name="workspace_role"))
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # SET NULL: deleting the inviter's account must not erase the invite's history.
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[InviteStatus] = mapped_column(
        Enum(InviteStatus, name="invite_status"),
        nullable=False,
        default=InviteStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="invites")
    # Read-only for the same reason as WorkspaceMembership.custom_role.
    custom_role: Mapped[WorkspaceRole | None] = relationship(
        primaryjoin="WorkspaceInvite.custom_role_id == WorkspaceRole.id",
        foreign_keys="WorkspaceInvite.custom_role_id",
        viewonly=True,
    )
