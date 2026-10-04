"""US-1 hardening: encryption keys, rotation, token refresh, rate limiter.

Endpoint-level OAuth behaviour lives in ``test_github_oauth.py``; this file
covers the pieces underneath it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text

from app.api.rate_limit import RateLimiter
from app.config import Settings, settings
from app.db.postgres import dispose_engine, get_engine
from app.github.oauth import OAuthToken
from app.main import app
from app.models import GitHubCredential, User
from app.security import (
    EncryptionKeyError,
    decrypt_secret,
    encrypt_secret,
    rotate_secret,
    validate_encryption_keys,
)
from app.services.github_credentials import (
    GitHubReauthRequired,
    get_github_access_token,
    save_github_token,
)
from scripts.rotate_token_key import rotate
from tests.test_github_oauth import FakeGitHub, oauth_client

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def new_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def keys(monkeypatch):
    """Point the app at a fresh current key; returns a setter for both settings."""

    def use(current: str | None, previous: list[str] | None = None) -> None:
        monkeypatch.setattr(
            settings, "token_encryption_key", SecretStr(current) if current else None
        )
        monkeypatch.setattr(
            settings,
            "token_encryption_previous_keys",
            SecretStr(",".join(previous)) if previous else None,
        )

    use(new_key())
    return use


# -- Key validation ------------------------------------------------------------


def test_malformed_key_fails_validation_without_revealing_it(keys):
    keys("definitely-not-a-fernet-key")

    with pytest.raises(EncryptionKeyError) as raised:
        validate_encryption_keys()

    assert "TOKEN_ENCRYPTION_KEY" in str(raised.value)
    assert "definitely-not-a-fernet-key" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_malformed_previous_key_is_named_separately(keys):
    keys(new_key(), ["not-a-key"])

    with pytest.raises(EncryptionKeyError, match="TOKEN_ENCRYPTION_PREVIOUS_KEYS"):
        validate_encryption_keys()


def test_previous_keys_without_a_current_key_are_rejected(keys):
    keys(None, [new_key()])

    with pytest.raises(EncryptionKeyError, match="TOKEN_ENCRYPTION_KEY is not"):
        validate_encryption_keys()


def test_no_keys_at_all_is_a_valid_startup(keys):
    keys(None)
    validate_encryption_keys()  # GitHub sign-in just reports 503


def test_blank_env_values_count_as_unset():
    configured = Settings(
        _env_file=None, token_encryption_key="  ", token_encryption_previous_keys=""
    )
    assert configured.token_encryption_key is None
    assert configured.token_encryption_previous_key_list == []


def test_app_refuses_to_start_with_a_malformed_key(keys):
    keys("not-a-key")
    # Startup fails before the lifespan yields, so its shutdown (which closes the
    # shared Neo4j driver) never runs.
    with pytest.raises(EncryptionKeyError):
        with TestClient(app):
            pass


# -- Rotation ------------------------------------------------------------------


def test_previous_key_decrypts_and_rotation_moves_to_the_current_key(keys):
    old, current = new_key(), new_key()
    keys(old)
    ciphertext = encrypt_secret("token")

    keys(current, [old])
    assert decrypt_secret(ciphertext) == "token"
    rotated = rotate_secret(ciphertext)

    keys(current)  # old key retired
    assert decrypt_secret(rotated) == "token"
    with pytest.raises(InvalidToken):
        decrypt_secret(ciphertext)


def _user(sessions, email: str) -> uuid.UUID:
    with sessions() as session:
        user = User(email=email, password_hash=None)
        session.add(user)
        session.commit()
        return user.id


def test_rotation_script_rewraps_readable_rows_and_purges_lost_ones(api_db, keys):
    _, sessions = api_db
    old, lost, current = new_key(), new_key(), new_key()

    keys(old)
    kept = _user(sessions, "kept@example.com")
    with sessions() as session:
        save_github_token(
            session, kept, OAuthToken("gho_kept", "", refresh_token="ghr_kept")
        )
        session.commit()
    keys(lost)
    orphan = _user(sessions, "orphan@example.com")
    with sessions() as session:
        save_github_token(session, orphan, OAuthToken("gho_orphan", ""))
        session.commit()

    keys(current, [old])
    with sessions() as session:
        report = rotate(session.connection(), purge_unreadable=True)
        session.commit()

    assert (report.rotated, report.unreadable, report.purged) == (1, 1, 1)
    keys(current)
    with sessions() as session:
        [credential] = session.scalars(select(GitHubCredential)).all()
        assert credential.user_id == kept
        assert (credential.access_token, credential.refresh_token) == (
            "gho_kept",
            "ghr_kept",
        )


def test_rotation_script_leaves_unreadable_rows_unless_asked(api_db, keys):
    _, sessions = api_db
    user_id = _user(sessions, "u@example.com")
    with sessions() as session:
        save_github_token(session, user_id, OAuthToken("gho", ""))
        session.commit()

    keys(new_key())
    with sessions() as session:
        report = rotate(session.connection())
        session.commit()
        remaining = session.execute(text("SELECT count(*) FROM github_credentials")).scalar()

    assert (report.unreadable, report.purged, remaining) == (1, 0, 1)


# -- Reading tokens: refresh and re-auth ---------------------------------------


@pytest.fixture
def stored(api_db, keys):
    """A fresh user with no credential yet; returns (sessions, user_id)."""
    _, sessions = api_db
    return sessions, _user(sessions, "octocat@example.com")


def read_token(sessions, user_id, github: FakeGitHub, at: datetime = NOW) -> str:
    client = oauth_client(github)
    try:
        with sessions() as session:
            return get_github_access_token(session, user_id, client, now=lambda: at)
    finally:
        client.close()


def save(sessions, user_id, token: OAuthToken, at: datetime = NOW) -> None:
    with sessions() as session:
        save_github_token(session, user_id, token, now=lambda: at)
        session.commit()


def credential_count(sessions) -> int:
    with sessions() as session:
        return len(session.scalars(select(GitHubCredential)).all())


EXPIRING = OAuthToken(
    "gho_old",
    "repo",
    expires_in=8 * 3600,
    refresh_token="ghr_old",
    refresh_token_expires_in=180 * 86400,
)


def test_non_expiring_token_is_returned_without_contacting_github(stored):
    sessions, user_id = stored
    save(sessions, user_id, OAuthToken("gho_classic", ""))
    github = FakeGitHub()

    assert read_token(sessions, user_id, github, at=NOW + timedelta(days=365)) == "gho_classic"
    assert github.requests == []


def test_unexpired_token_is_returned_as_is(stored):
    sessions, user_id = stored
    save(sessions, user_id, EXPIRING)
    github = FakeGitHub()

    assert read_token(sessions, user_id, github, at=NOW + timedelta(hours=1)) == "gho_old"
    assert github.requests == []


def test_token_about_to_expire_is_refreshed_and_both_tokens_replaced(stored):
    sessions, user_id = stored
    save(sessions, user_id, EXPIRING)
    github = FakeGitHub()
    github.refresh_response = httpx.Response(
        200,
        json={
            "access_token": "gho_new",
            "scope": "repo",
            "expires_in": 28800,
            "refresh_token": "ghr_new",
            "refresh_token_expires_in": 15897600,
        },
    )
    later = NOW + timedelta(hours=7, minutes=58)  # inside the 5-minute skew

    assert read_token(sessions, user_id, github, at=later) == "gho_new"

    [refresh] = github.token_requests()
    assert (refresh["grant_type"], refresh["refresh_token"]) == ("refresh_token", "ghr_old")
    with sessions() as session:
        credential = session.scalar(select(GitHubCredential))
        assert (credential.access_token, credential.refresh_token) == ("gho_new", "ghr_new")
        assert credential.access_token_expires_at.replace(
            tzinfo=timezone.utc
        ) == later + timedelta(hours=8)


def test_rejected_refresh_discards_the_credential(stored):
    sessions, user_id = stored
    save(sessions, user_id, EXPIRING)
    github = FakeGitHub()  # refresh_response is an error by default

    with pytest.raises(GitHubReauthRequired):
        read_token(sessions, user_id, github, at=NOW + timedelta(hours=9))
    assert credential_count(sessions) == 0


def test_expired_refresh_token_requires_reauth_without_contacting_github(stored):
    sessions, user_id = stored
    save(sessions, user_id, EXPIRING)
    github = FakeGitHub()

    with pytest.raises(GitHubReauthRequired):
        read_token(sessions, user_id, github, at=NOW + timedelta(days=181))
    assert github.requests == []
    assert credential_count(sessions) == 0


def test_token_under_a_lost_key_requires_reauth_instead_of_crashing(stored, keys):
    sessions, user_id = stored
    save(sessions, user_id, OAuthToken("gho_classic", ""))
    keys(new_key())

    with pytest.raises(GitHubReauthRequired):
        read_token(sessions, user_id, FakeGitHub())
    assert credential_count(sessions) == 0


def test_user_without_a_credential_requires_reauth(stored):
    sessions, user_id = stored
    with pytest.raises(GitHubReauthRequired):
        read_token(sessions, user_id, FakeGitHub())


# -- Rate limiter --------------------------------------------------------------


class _Request:
    def __init__(self, host: str):
        self.client = type("Client", (), {"host": host})()


def test_rate_limiter_window_slides_and_counts_clients_separately():
    clock = [0.0]
    limiter = RateLimiter(2, window_seconds=60, clock=lambda: clock[0])

    limiter(_Request("1.1.1.1"))
    limiter(_Request("1.1.1.1"))
    with pytest.raises(HTTPException) as raised:
        limiter(_Request("1.1.1.1"))
    assert raised.value.status_code == 429
    assert raised.value.headers["Retry-After"] == "60"

    limiter(_Request("2.2.2.2"))  # another client is unaffected

    clock[0] = 60.5  # the first hits have aged out
    limiter(_Request("1.1.1.1"))


# -- Logging -------------------------------------------------------------------


def test_engine_hides_bound_parameters_from_logs_and_errors():
    # create_engine does not connect, so this needs no running Postgres.
    try:
        assert get_engine().hide_parameters is True
    finally:
        dispose_engine()
