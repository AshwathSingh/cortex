"""T-1.1: GitHub OAuth web flow -- authorize URL, code exchange, identity.

Separate from ``client.py``: that client paginates repository data once a token
exists; this one runs before Cortex knows who the user is. GitHub's JSON is
validated with Pydantic before anything is written to Postgres.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_BASE = "https://api.github.com"


class OAuthError(Exception):
    """GitHub rejected the sign-in, or returned an identity Cortex cannot use."""


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _TokenResponse(_Payload):
    access_token: str
    scope: str = ""


class _GitHubProfile(_Payload):
    id: int
    login: str
    name: str | None = None
    avatar_url: str | None = None


class _GitHubEmail(_Payload):
    email: str
    primary: bool = False
    verified: bool = False


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    scope: str

    def __repr__(self) -> str:
        return f"OAuthToken(scope={self.scope!r})"


@dataclass(frozen=True)
class GitHubIdentity:
    id: int
    login: str
    name: str | None
    avatar_url: str | None
    email: str  # verified; the primary address when it is verified


def authorize_url(*, client_id: str, redirect_uri: str, scope: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


class GitHubOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        transport: httpx.BaseTransport | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = httpx.Client(transport=transport, timeout=15)

    def close(self) -> None:
        self._http.close()

    def exchange_code(self, code: str) -> OAuthToken:
        resp = self._http.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri,
            },
        )
        if resp.status_code != 200:
            raise OAuthError(f"token exchange failed: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as e:
            raise OAuthError("malformed token response") from e
        # GitHub reports a bad or expired code as 200 {"error": ...}, not a 4xx.
        if isinstance(body, dict) and "error" in body:
            raise OAuthError(str(body["error"]))
        try:
            token = _TokenResponse.model_validate(body)
        except ValidationError as e:
            raise OAuthError("malformed token response") from e
        return OAuthToken(access_token=token.access_token, scope=token.scope)

    def fetch_identity(self, access_token: str) -> GitHubIdentity:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        profile_resp = self._http.get(f"{API_BASE}/user", headers=headers)
        emails_resp = self._http.get(f"{API_BASE}/user/emails", headers=headers)
        if profile_resp.status_code != 200 or emails_resp.status_code != 200:
            raise OAuthError("GitHub rejected the access token")

        try:
            profile = _GitHubProfile.model_validate(profile_resp.json())
            emails = [_GitHubEmail.model_validate(e) for e in emails_resp.json()]
        except (ValidationError, TypeError, ValueError) as e:
            raise OAuthError("malformed GitHub profile") from e

        # Only a verified address may identify a Cortex account; an unverified one
        # could belong to someone else.
        verified = [e for e in emails if e.verified]
        if not verified:
            raise OAuthError("GitHub account has no verified email address")
        email = next((e for e in verified if e.primary), verified[0]).email

        return GitHubIdentity(
            id=profile.id,
            login=profile.login,
            name=profile.name,
            avatar_url=profile.avatar_url,
            email=email,
        )
