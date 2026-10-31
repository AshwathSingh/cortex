"""T-8.2: a workspace's authorisation to read a chat provider, encrypted at rest.

Deliberately not an extension of ``github_credentials``. That table keys on
``user_id``: a GitHub token identifies a *person*, is obtained during sign-in,
and follows them between workspaces. A Slack or Discord connection is the
opposite -- it belongs to the Cortex workspace, is created by whoever holds
``sources.write``, and must keep working after that person leaves. Different
owner, different lifetime, different table.

One row per (workspace, provider): the story is "connect *a* Slack workspace",
and re-authorising replaces the connection rather than accumulating a second
one. Connecting a different team to the same Cortex workspace is therefore a
replacement, which is also what makes ``external_ref`` safe to use as the
``data_sources`` key.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import EncryptedString

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


class SourceCredential(Base):
    """A connected chat provider. Must never be serialised into a response."""

    __tablename__ = "source_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", name="uq_source_credential_kind"),
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
    #: "slack" or "discord"; a plain string for the same reason
    #: ``DataSource.kind`` is one.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Slack team id (``T…``) or Discord guild id. The provider's own immutable
    #: handle for the thing we were authorised against -- never a display name,
    #: because this is the key ``data_sources`` rows are matched on.
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    #: What to call it on screen. Renameable, so never used as a key.
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # NULL for Discord, and that is not an oversight. Slack's OAuth exchange
    # returns a bot token scoped to the team that just installed Cortex, so
    # there is a per-workspace secret to keep. Discord's bot token is a single
    # application-wide secret in config (``discord_bot_token``) and the install
    # flow only establishes *which guild* the bot was added to -- copying one
    # server-wide secret into every row would mean rewriting them all to rotate
    # it. ``app.services.chat_credentials`` resolves both to a usable token.
    access_token: Mapped[str | None] = mapped_column(EncryptedString)
    scope: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    #: Who connected it. SET NULL rather than CASCADE: losing a member must not
    #: silently disconnect the workspace's Slack.
    installed_by: Mapped[uuid.UUID | None] = mapped_column(
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

    workspace: Mapped["Workspace"] = relationship()
    installer: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        # The default repr would include the decrypted token.
        return (
            f"SourceCredential(workspace_id={self.workspace_id!r}, "
            f"kind={self.kind!r}, external_ref={self.external_ref!r})"
        )


class SourceInstallTransaction(Base):
    """An in-flight "connect this provider" authorisation.

    Kept apart from ``oauth_transactions`` because it answers a different
    question. That one binds a sign-in to a browser; this one has to remember
    *which workspace* and *which provider* a callback belongs to, since the
    provider hands back nothing that identifies either. It also has no PKCE
    verifier: neither Slack's nor Discord's authorisation-code flow supports
    PKCE for confidential clients, so the client secret is what proves the
    exchange.
    """

    __tablename__ = "source_install_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # sha256 of the state, like session tokens: a database read alone cannot
    # forge a callback.
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The user who started it. The callback re-checks their permission on the
    #: workspace, so a role revoked mid-flow takes effect before anything is
    #: stored.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
