"""An in-flight GitHub sign-in: created at login, consumed by the first valid callback."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OAuthTransaction(Base):
    """Server-side half of the OAuth ``state``; the browser holds the other half
    in a cookie. Deleting the row on the first valid callback makes the state
    single-use, so a replayed callback is rejected before GitHub is contacted.
    """

    __tablename__ = "oauth_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # sha256 of the state, like session tokens: a database read alone cannot
    # forge a callback.
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # PKCE verifier. Stored plaintext on purpose: it lives at most ten minutes,
    # is deleted on use, and is useless without the browser's one-time code.
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
