"""T-8.2: the authorisation exchanges that connect Slack and Discord.

Two providers, two different things being authorised, which is why this is not
one client with a provider flag:

Slack is a token flow like GitHub's. A member with ``sources.write`` installs
Cortex into their Slack team and the exchange hands back a bot token scoped to
*that team*, which is the credential every later read uses.

Discord is an installation flow. Its HTTP API will not return channel history
for a user access token at all -- ``GET /channels/{id}/messages`` requires a bot
token -- so the thing being authorised is the bot joining a guild. The exchange
is still performed, because it is the only way to learn *which* guild the user
added the bot to and what it is called, but the returned user token is then
discarded: reads use the application's own bot token from config.

Both report failure as ``ChatInstallError``. Neither flow uses PKCE: Slack and
Discord both treat this as a confidential client, so the client secret is what
proves the exchange, and there is no verifier to store.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_API_BASE = "https://slack.com/api"

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_BASE = "https://discord.com/api/v10"


class ChatInstallError(Exception):
    """The provider rejected the authorisation, or answered unusably.

    ``code`` is the provider's own error slug when it sent one (Slack's
    ``invalid_code``, for instance) and None for transport or shape failures,
    which may be temporary.
    """

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ChatInstall:
    """What an exchange established about the connection.

    ``access_token`` is None for Discord, whose reads use the application-wide
    bot token instead -- see ``app.models.source_credential``.
    """

    external_ref: str
    display_name: str
    access_token: str | None
    scope: str

    def __repr__(self) -> str:
        return (
            f"ChatInstall(external_ref={self.external_ref!r}, "
            f"display_name={self.display_name!r}, scope={self.scope!r})"
        )


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _SlackTeam(_Payload):
    id: str
    name: str = ""


class _SlackTokenResponse(_Payload):
    access_token: str
    scope: str = ""
    team: _SlackTeam


class _DiscordGuild(_Payload):
    id: str
    name: str = ""


class _DiscordTokenResponse(_Payload):
    scope: str = ""
    guild: _DiscordGuild


def slack_authorize_url(
    *, client_id: str, redirect_uri: str, scope: str, state: str
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "scope": scope,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{SLACK_AUTHORIZE_URL}?{query}"


def discord_authorize_url(
    *, client_id: str, redirect_uri: str, permissions: str, state: str
) -> str:
    """The bot-invite URL. ``scope=bot`` is what makes Discord show the
    "add to server" picker and the permission list, rather than a sign-in."""
    query = urlencode(
        {
            "client_id": client_id,
            "scope": "bot",
            "permissions": permissions,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    return f"{DISCORD_AUTHORIZE_URL}?{query}"


class _ExchangeClient:
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

    def _post(self, url: str, data: dict[str, str]) -> dict:
        try:
            resp = self._http.post(
                url, headers={"Accept": "application/json"}, data=data
            )
        except httpx.TransportError as e:
            raise ChatInstallError("could not reach the provider") from e
        if resp.status_code != 200:
            raise ChatInstallError(f"token request failed: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as e:
            raise ChatInstallError("malformed token response") from e
        if not isinstance(body, dict):
            raise ChatInstallError("malformed token response")
        return body


class SlackOAuthClient(_ExchangeClient):
    def exchange_code(self, code: str) -> ChatInstall:
        body = self._post(
            SLACK_TOKEN_URL,
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri,
            },
        )
        # Slack answers a rejected code with 200 {"ok": false, "error": ...}.
        if not body.get("ok", False):
            error = str(body.get("error", "unknown_error"))
            raise ChatInstallError(error, code=error)
        try:
            token = _SlackTokenResponse.model_validate(body)
        except ValidationError as e:
            raise ChatInstallError("malformed token response") from e
        return ChatInstall(
            external_ref=token.team.id,
            display_name=token.team.name or token.team.id,
            access_token=token.access_token,
            scope=token.scope,
        )


class DiscordOAuthClient(_ExchangeClient):
    def exchange_code(self, code: str) -> ChatInstall:
        body = self._post(
            DISCORD_TOKEN_URL,
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
            },
        )
        if "error" in body:
            error = str(body["error"])
            raise ChatInstallError(error, code=error)
        try:
            token = _DiscordTokenResponse.model_validate(body)
        except ValidationError as e:
            # A response with no `guild` means the user completed the flow
            # without adding the bot anywhere, so there is nothing to connect.
            raise ChatInstallError("Discord did not report a server") from e
        return ChatInstall(
            external_ref=token.guild.id,
            display_name=token.guild.name or token.guild.id,
            # Deliberately dropped: reads use the bot token from config.
            access_token=None,
            scope=token.scope,
        )
