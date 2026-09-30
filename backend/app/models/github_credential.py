"""A user's GitHub OAuth access token, encrypted at rest (US-1)."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import EncryptedString

if TYPE_CHECKING:
    from app.models.user import User


class GitHubCredential(Base):
    """Kept apart from ``users`` so the token is loaded only when something calls
    GitHub on the user's behalf, never alongside an ordinary profile read. It must
    never be serialised into an API response.
    """

    __tablename__ = "github_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    access_token: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="github_credential")

    def __repr__(self) -> str:
        # The default repr would include the decrypted token.
        return f"GitHubCredential(user_id={self.user_id!r}, scope={self.scope!r})"
