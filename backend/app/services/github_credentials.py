"""Storing and reading a user's GitHub OAuth tokens (US-1).

Two rules keep a lost or rotated encryption key from locking anyone out:

- Saving never reads the old row, so sign-in works even when the stored
  ciphertext is unreadable. A fresh sign-in is always the recovery path.
- Reading treats a credential that can never work again -- unreadable, refresh
  token expired, or refresh rejected as ``bad_refresh_token`` -- the same way:
  delete it and raise ``GitHubReauthRequired``, so the caller can send the user
  back through GitHub sign-in rather than fail with a 500. A failure that may be
  temporary (GitHub 429/5xx, network error) keeps the credential and raises
  ``GitHubUnavailable`` instead.
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.github.oauth import GitHubOAuthClient, OAuthError, OAuthToken
from app.models import GitHubCredential

# Refresh this long before expiry, so a token is not handed out to die mid-request.
EXPIRY_SKEW = timedelta(minutes=5)

# Token-endpoint errors that mean this refresh token will never work again.
# Anything else -- including our own misconfiguration, such as
# incorrect_client_credentials -- must not wipe users' credentials.
PERMANENT_REFRESH_ERRORS = frozenset({"bad_refresh_token"})

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GitHubReauthRequired(Exception):
    """The user has no usable GitHub token and must sign in with GitHub again."""


class GitHubUnavailable(Exception):
    """Refreshing failed in a way that may be temporary; the credential is kept.
    Retry later."""


def _expiry(now: datetime, seconds: int | None) -> datetime | None:
    return None if seconds is None else now + timedelta(seconds=seconds)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite (tests) returns naive datetimes for timezone=True columns; Postgres
    # does not. Both are stored as UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def save_github_token(
    session: Session, user_id: uuid.UUID, token: OAuthToken, *, now: Clock = _utcnow
) -> None:
    """Replace the user's stored token. Does not commit."""
    issued_at = now()
    session.execute(delete(GitHubCredential).where(GitHubCredential.user_id == user_id))
    session.add(
        GitHubCredential(
            user_id=user_id,
            access_token=token.access_token,
            scope=token.scope,
            access_token_expires_at=_expiry(issued_at, token.expires_in),
            refresh_token=token.refresh_token,
            refresh_token_expires_at=_expiry(issued_at, token.refresh_token_expires_in),
        )
    )


def _discard(session: Session, user_id: uuid.UUID) -> GitHubReauthRequired:
    session.rollback()
    session.execute(delete(GitHubCredential).where(GitHubCredential.user_id == user_id))
    session.commit()
    return GitHubReauthRequired()


def get_github_access_token(
    session: Session,
    user_id: uuid.UUID,
    oauth: GitHubOAuthClient,
    *,
    now: Clock = _utcnow,
) -> str:
    """A currently valid access token for the user, refreshing it if needed.

    Commits when it refreshes or discards a credential. Raises
    ``GitHubReauthRequired`` when there is no usable token, and
    ``GitHubUnavailable`` when a refresh failed but may succeed later.
    """
    try:
        # FOR UPDATE: GitHub refresh tokens are single-use, so two requests must
        # not refresh the same credential concurrently.
        credential = session.get(GitHubCredential, user_id, with_for_update=True)
    except InvalidToken:
        # Encrypted under a key that is no longer configured.
        raise _discard(session, user_id) from None
    if credential is None:
        raise GitHubReauthRequired()

    current = now()
    access_expires = _aware(credential.access_token_expires_at)
    if access_expires is None or access_expires - EXPIRY_SKEW > current:
        return credential.access_token

    refresh_expires = _aware(credential.refresh_token_expires_at)
    if credential.refresh_token is None or (
        refresh_expires is not None and refresh_expires <= current
    ):
        raise _discard(session, user_id)

    try:
        token = oauth.refresh(credential.refresh_token)
    except OAuthError as error:
        if error.code in PERMANENT_REFRESH_ERRORS:
            raise _discard(session, user_id) from None
        session.rollback()  # release the row lock; the credential is untouched
        raise GitHubUnavailable() from error
    except httpx.TransportError as error:
        session.rollback()
        raise GitHubUnavailable() from error

    credential.access_token = token.access_token
    credential.scope = token.scope or credential.scope
    credential.access_token_expires_at = _expiry(current, token.expires_in)
    # GitHub rotates the refresh token on every use; keep the old one only if a
    # response ever omits it.
    if token.refresh_token is not None:
        credential.refresh_token = token.refresh_token
        credential.refresh_token_expires_at = _expiry(
            current, token.refresh_token_expires_in
        )
    session.commit()
    return token.access_token
