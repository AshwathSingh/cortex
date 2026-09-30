"""T-1.5: GitHub OAuth sign-in, tested against the US-1 acceptance criteria.

GitHub is replaced by an ``httpx.MockTransport``; everything on the Cortex side
-- state check, user/credential writes, session cookie, ``get_current_user`` --
runs for real against the in-memory database from ``api_db``.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, text

from app.api.auth import OAUTH_STATE_COOKIE, get_github_oauth_client
from app.config import settings
from app.github.oauth import GitHubOAuthClient, OAuthError
from app.main import app
from app.models import GitHubCredential, User, UserSession
from app.security import decrypt_secret, encrypt_secret, hash_password

ACCESS_TOKEN = "gho_test_access_token_do_not_leak"
PROFILE = {
    "id": 583231,
    "login": "octocat",
    "name": "The Octocat",
    "avatar_url": "https://avatars.githubusercontent.com/u/583231",
}
EMAILS = [
    {"email": "octo-old@example.com", "primary": False, "verified": True},
    {"email": "Octocat@Example.com", "primary": True, "verified": True},
]


class FakeGitHub:
    """Programmable stand-in for github.com and api.github.com."""

    def __init__(self):
        self.token_response: httpx.Response = httpx.Response(
            200, json={"access_token": ACCESS_TOKEN, "scope": "read:user,user:email"}
        )
        self.profile = dict(PROFILE)
        self.emails = list(EMAILS)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/login/oauth/access_token":
            return self.token_response
        if request.headers.get("Authorization") != f"Bearer {ACCESS_TOKEN}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/user":
            return httpx.Response(200, json=self.profile)
        if request.url.path == "/user/emails":
            return httpx.Response(200, json=self.emails)
        return httpx.Response(404)


@pytest.fixture
def oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "github_client_id", "test-client-id")
    monkeypatch.setattr(settings, "github_client_secret", SecretStr("test-secret"))
    monkeypatch.setattr(
        settings, "token_encryption_key", SecretStr(Fernet.generate_key().decode())
    )


@pytest.fixture
def github(api_db, oauth_settings):
    fake = FakeGitHub()

    def override():
        client = GitHubOAuthClient(
            client_id="test-client-id",
            client_secret="test-secret",
            redirect_uri=settings.github_oauth_redirect_uri,
            transport=httpx.MockTransport(fake),
        )
        try:
            yield client
        finally:
            client.close()

    app.dependency_overrides[get_github_oauth_client] = override
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_github_oauth_client, None)


def start_login(client) -> str:
    """Hit the login endpoint like the browser does; return the state it issued."""
    response = client.get("/api/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def finish_login(client, state: str, code: str = "valid-code"):
    return client.post("/api/auth/github/callback", json={"code": code, "state": state})


def count(sessions, model) -> int:
    with sessions() as session:
        return len(session.scalars(select(model)).all())


# -- Login redirect ------------------------------------------------------------


def test_login_redirects_to_github_with_state_bound_to_browser(api_db, oauth_settings):
    client, _ = api_db

    response = client.get("/api/auth/github/login", follow_redirects=False)

    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == (
        "https://github.com/login/oauth/authorize"
    )
    query = parse_qs(location.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == [settings.github_oauth_redirect_uri]
    assert query["state"][0] == client.cookies.get(OAUTH_STATE_COOKIE)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/api/auth/github" in cookie
    assert "test-secret" not in response.headers["location"]


def test_login_is_unavailable_until_oauth_is_configured(api_db, monkeypatch):
    client, _ = api_db
    monkeypatch.setattr(settings, "github_client_id", None)

    response = client.get("/api/auth/github/login", follow_redirects=False)

    assert response.status_code == 503


# -- Successful sign-in --------------------------------------------------------


def test_first_sign_in_creates_user_session_and_workspace(api_db, github):
    client, sessions = api_db

    response = finish_login(client, start_login(client))

    assert response.status_code == 200
    assert response.json()["email"] == "octocat@example.com"  # primary, lowercased
    assert response.json()["display_name"] == "The Octocat"
    assert "HttpOnly" in response.headers["set-cookie"]
    # The one-time state is spent.
    assert client.cookies.get(OAUTH_STATE_COOKIE) is None

    # AC: the authenticated session grants access to protected endpoints, and the
    # Workspace Selector has a workspace to show.
    assert client.get("/api/auth/me").status_code == 200
    workspaces = client.get("/api/workspaces")
    assert workspaces.status_code == 200
    assert [w["role"] for w in workspaces.json()] == ["OWNER"]

    with sessions() as session:
        user = session.scalar(select(User))
        assert user.github_id == PROFILE["id"]
        assert user.github_login == "octocat"
        assert user.password_hash is None
        assert user.email_verified_at is not None


def test_access_token_is_encrypted_at_rest_and_never_returned(api_db, github):
    client, sessions = api_db

    response = finish_login(client, start_login(client))

    assert ACCESS_TOKEN not in response.text
    assert ACCESS_TOKEN not in str(response.headers)
    assert ACCESS_TOKEN not in client.get("/api/auth/me").text

    with sessions() as session:
        stored = session.execute(
            text("SELECT access_token FROM github_credentials")
        ).scalar_one()
        assert ACCESS_TOKEN not in stored
        assert decrypt_secret(stored) == ACCESS_TOKEN
        # The ORM hands back plaintext for code that calls GitHub for the user.
        credential = session.scalar(select(GitHubCredential))
        assert credential.access_token == ACCESS_TOKEN
        assert ACCESS_TOKEN not in repr(credential)


def test_returning_user_reuses_account_and_refreshes_token(api_db, github):
    client, sessions = api_db
    finish_login(client, start_login(client))

    github.profile["login"] = "octocat-renamed"
    response = finish_login(client, start_login(client))

    assert response.status_code == 200
    assert count(sessions, User) == 1
    assert count(sessions, GitHubCredential) == 1
    assert len(client.get("/api/workspaces").json()) == 1  # no second default
    with sessions() as session:
        assert session.scalar(select(User.github_login)) == "octocat-renamed"


# -- Rejected sign-in: 401, nothing created ------------------------------------


def assert_rejected(response, sessions):
    assert response.status_code == 401
    assert "set-cookie" not in response.headers or (
        settings.session_cookie_name not in response.headers["set-cookie"]
    )
    assert count(sessions, User) == 0
    assert count(sessions, UserSession) == 0
    assert count(sessions, GitHubCredential) == 0


def test_state_mismatch_is_rejected_before_contacting_github(api_db, github):
    client, sessions = api_db
    start_login(client)

    response = finish_login(client, "forged-state")

    assert_rejected(response, sessions)
    assert github.requests == []


def test_callback_without_a_login_started_in_this_browser_is_rejected(api_db, github):
    client, sessions = api_db

    response = finish_login(client, "any-state")

    assert_rejected(response, sessions)
    assert github.requests == []


def test_code_rejected_by_github_aborts_with_401(api_db, github):
    client, sessions = api_db
    github.token_response = httpx.Response(
        200, json={"error": "bad_verification_code"}
    )

    response = finish_login(client, start_login(client))

    assert_rejected(response, sessions)
    assert client.get("/api/auth/me").status_code == 401


def test_github_account_without_verified_email_is_rejected(api_db, github):
    client, sessions = api_db
    github.emails = [{"email": "octocat@example.com", "primary": True, "verified": False}]

    assert_rejected(finish_login(client, start_login(client)), sessions)


def test_deactivated_user_cannot_sign_in(api_db, github):
    client, sessions = api_db
    finish_login(client, start_login(client))
    client.cookies.clear()
    with sessions() as session:
        session.scalar(select(User)).is_active = False
        session.commit()

    response = finish_login(client, start_login(client))

    assert response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_existing_password_account_is_not_silently_linked(api_db, github):
    client, sessions = api_db
    with sessions() as session:
        session.add(
            User(
                email="octocat@example.com",
                password_hash=hash_password("a-secure-password-with-15-characters"),
            )
        )
        session.commit()

    response = finish_login(client, start_login(client))

    assert response.status_code == 409
    with sessions() as session:
        assert session.scalar(select(User.github_id)) is None
    assert count(sessions, GitHubCredential) == 0


def test_github_unreachable_is_a_502(api_db, github):
    client, sessions = api_db

    def unreachable(request):
        raise httpx.ConnectError("down", request=request)

    app.dependency_overrides[get_github_oauth_client] = lambda: GitHubOAuthClient(
        client_id="x", client_secret="y", redirect_uri="z",
        transport=httpx.MockTransport(unreachable),
    )

    response = finish_login(client, start_login(client))

    assert response.status_code == 502
    assert count(sessions, User) == 0


# -- Units ---------------------------------------------------------------------


def test_encryption_round_trips_and_is_not_deterministic(oauth_settings):
    first, second = encrypt_secret("secret"), encrypt_secret("secret")
    assert first != second
    assert decrypt_secret(first) == decrypt_secret(second) == "secret"


def test_encryption_refuses_to_run_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_key", None)
    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        encrypt_secret("secret")


def test_oauth_client_raises_on_malformed_token_response():
    client = GitHubOAuthClient(
        client_id="x", client_secret="y", redirect_uri="z",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")),
    )
    with pytest.raises(OAuthError):
        client.exchange_code("code")
