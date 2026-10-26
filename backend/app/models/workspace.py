"""Workspace ownership and membership models."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
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
    from app.models.data_source import DataSource
    from app.models.user import User


class Role(str, enum.Enum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    data_sources: Mapped[list["DataSource"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    custom_roles: Mapped[list["WorkspaceRole"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceRole(Base):
    """A custom role defined by a workspace, holding the permissions its creator chose.

    The built-in OWNER/EDITOR/VIEWER are not rows here; see ``app.permissions``.
    """

    __tablename__ = "workspace_roles"
    __table_args__ = (
        # Target of the composite foreign key on memberships (see there).
        UniqueConstraint("id", "workspace_id", name="uq_workspace_roles_id_workspace"),
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
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # List of ``Permission`` values; see app.permissions.parse_permissions.
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="custom_roles")


# Names are unique per workspace, case-insensitively. Declared after the class so the
# index is built on the real column (a string here would index the literal 'name').
Index(
    "uq_workspace_roles_name",
    WorkspaceRole.workspace_id,
    func.lower(WorkspaceRole.name),
    unique=True,
)


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_workspace"),
        # A custom role must belong to the membership's own workspace: the pair
        # (custom_role_id, workspace_id) has to match a role row's (id, workspace_id).
        # A NULL custom_role_id (built-in role) skips the check. No ON DELETE action:
        # NO ACTION is checked at end of statement, so a workspace delete may cascade
        # to roles and memberships together, while deleting a role still in use is
        # refused. RESTRICT would fire mid-cascade and block workspace deletion.
        ForeignKeyConstraint(
            ["custom_role_id", "workspace_id"],
            ["workspace_roles.id", "workspace_roles.workspace_id"],
            name="fk_membership_custom_role",
        ),
        # A member holds a built-in role or a custom one, never both and never neither.
        CheckConstraint(
            "(role IS NULL) <> (custom_role_id IS NULL)",
            name="ck_membership_exactly_one_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Built-in role, or None when ``custom_role_id`` is set.
    role: Mapped[Role | None] = mapped_column(Enum(Role, name="workspace_role"))
    # Foreign key is composite and declared in __table_args__.
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    # Read-only: the composite foreign key also spans workspace_id, which this
    # relationship must never write. Assign roles through ``custom_role_id``.
    custom_role: Mapped[WorkspaceRole | None] = relationship(
        primaryjoin="WorkspaceMembership.custom_role_id == WorkspaceRole.id",
        foreign_keys="WorkspaceMembership.custom_role_id",
        viewonly=True,
    )
