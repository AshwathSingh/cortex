"""T-8.2: connecting Slack and Discord to a workspace.

The relational half is real (in-memory), so `get_current_user` and
`load_workspace_for_user` genuinely run; only the provider's token endpoint is
faked. What is being pinned here is the authorisation, not the HTTP shape: who
may start an install, that the state is single-use and bound to the browser,
that the permission is re-checked after the user comes back, and that the
stored token is encrypted and never returned.
"""

import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, text

from app.api.sources import (
    INSTALL_STATE_COOKIE,
    get_oauth_client_builder,
)
from app.config import settings
from app.main import app
from app.models import (
    Role,
    SourceCredential,
    SourceInstallTransaction,
    WorkspaceMembership,
)
from app.services.chat_credentials import (
    SourceCredentialMissing,
    get_chat_credential,
)
from app.sources.chat_oauth import DiscordOAuthClient, SlackOAuthClient
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID

TEAM = {"id": "T0ACME", "name": "Acme"}
GUILD = {"id": "912340000000000000", "name": "Acme Guild"}
BOT_TOKEN = "xoxb-acme-bot"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """A server with both providers configured and a working encryption key."""
    monkeypatch.setattr(settings, "token_encryption_key", SecretStr(Fernet.generate_key().decode()))
    monkeypatch.setattr(settings, "token_encryption_previous_keys", None)
    monkeypatch.setattr(settings, "slack_client_id", "slack-client")
    monkeypatch.setattr(settings, "slack_client_secret", SecretStr("slack-secret"))
    monkeypatch.setattr(settings, "discord_client_id", "discord-client")
    monkeypatch.setattr(settings, "discord_client_secret", SecretStr("discord-secret"))
    monkeypatch.setattr(settings, "discord_bot_token", SecretStr("discord-bot-token"))
    yield
    app.dependency_overrides.pop(get_oauth_client_builder, None)


def fake_provider(handler):
    """Install an exchange client whose HTTP goes to ``handler``."""

    def builder(kind: str):
        transport = httpx.MockTransport(handler)
        cls = SlackOAuthClient if kind == "slack" else DiscordOAuthClient
        return cls(
            client_id="id",
            client_secret="secret",
            redirect_uri="http://localhost:3000/cb",
            transport=transport,
        )

    app.dependency_overrides[get_oauth_client_builder] = lambda: builder


def slack_ok(request):
    return httpx.Response(
        200,
        json={
            "ok": True,
            "access_token": BOT_TOKEN,
            "scope": "channels:read,channels:history",
            "team": TEAM,
        },
    )


def discord_ok(request):
    return httpx.Response(200, json={"scope": "bot", "guild": GUILD})


def start(client, kind="slack", workspace_id=TEST_WORKSPACE_ID):
    return client.get(
        f"/api/sources/{kind}/install",
        params={"workspace_id": workspace_id},
        follow_redirects=False,
    )


def finish(client, kind="slack", *, code="the-code", state=None):
    state = state if state is not None else client.cookies.get(INSTALL_STATE_COOKIE)
    return client.post(
        f"/api/sources/{kind}/callback", json={"code": code, "state": state}
    )


def credentials(sessions) -> list[SourceCredential]:
    with sessions() as session:
        return list(session.scalars(select(SourceCredential)))


# -- Starting an install -------------------------------------------------------


def test_an_install_redirects_to_slack_and_binds_the_state_to_the_browser(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)

    response = start(client)

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://slack.com/oauth/v2/authorize?"
    )
    assert "channels%3Ahistory" in response.headers["location"]
    state = client.cookies.get(INSTALL_STATE_COOKIE)
    assert state
    # Server-side half, so a cookie alone cannot name a workspace.
    with sessions() as session:
        (row,) = session.scalars(select(SourceInstallTransaction)).all()
        assert row.kind == "slack"
        assert row.workspace_id == uuid.UUID(TEST_WORKSPACE_ID)
        # The state itself is never stored, only its hash.
        assert state not in row.state_hash


def test_a_discord_install_asks_for_the_bot_and_its_permissions(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)

    location = start(client, "discord").headers["location"]

    assert location.startswith("https://discord.com/oauth2/authorize?")
    assert "scope=bot" in location
    assert "permissions=66560" in location


def test_a_viewer_cannot_start_an_install(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.VIEWER)

    response = start(client)

    assert response.status_code == 403
    assert "sources.write" in response.json()["detail"]
    assert client.cookies.get(INSTALL_STATE_COOKIE) is None


def test_a_non_member_cannot_discover_the_workspace_exists(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)

    response = start(client)

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this workspace"


def test_an_anonymous_caller_cannot_start_an_install(api_db):
    client, _ = api_db
    assert start(client).status_code == 401


def test_an_unconfigured_provider_is_a_503(api_db, monkeypatch):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    monkeypatch.setattr(settings, "slack_client_id", None)

    response = start(client)

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


# -- Finishing an install ------------------------------------------------------


def test_slack_stores_the_team_and_its_token_encrypted(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)

    response = finish(client)

    assert response.status_code == 200
    assert response.json() == {
        "kind": "slack",
        "external_ref": "T0ACME",
        "display_name": "Acme",
        "installed_by_name": "member",
        "workspace_id": TEST_WORKSPACE_ID,
    }
    (row,) = credentials(sessions)
    assert row.access_token == BOT_TOKEN  # decrypted transparently on load
    with sessions() as session:
        stored = session.execute(
            text("SELECT access_token FROM source_credentials")
        ).scalar_one()
    # The plaintext never reaches the database, its logs or its backups.
    assert BOT_TOKEN not in stored


def test_discord_stores_the_guild_and_no_token(api_db):
    """Discord's bot token is one application-wide secret in config, so there is
    no per-workspace token to keep -- only which guild the bot was added to."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(discord_ok)
    start(client, "discord")

    assert finish(client, "discord").status_code == 200

    (row,) = credentials(sessions)
    assert (row.kind, row.external_ref, row.display_name) == (
        "discord",
        GUILD["id"],
        "Acme Guild",
    )
    assert row.access_token is None
    # Reads still resolve to a usable token, from config.
    with sessions() as session:
        resolved = get_chat_credential(
            session, workspace_id=uuid.UUID(TEST_WORKSPACE_ID), kind="discord"
        )
    assert resolved.token == "discord-bot-token"


def test_a_credential_is_never_rendered_with_its_token(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)
    finish(client)

    (row,) = credentials(sessions)

    assert BOT_TOKEN not in repr(row)


def test_the_state_is_single_use(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)
    state = client.cookies.get(INSTALL_STATE_COOKIE)

    assert finish(client, state=state).status_code == 200
    # A replayed callback is rejected before the provider is contacted again.
    assert finish(client, state=state).status_code == 401
    assert len(credentials(sessions)) == 1


def test_a_callback_without_the_browsers_cookie_is_rejected(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)
    state = client.cookies.get(INSTALL_STATE_COOKIE)
    client.cookies.delete(INSTALL_STATE_COOKIE)

    assert finish(client, state=state).status_code == 401
    assert credentials(sessions) == []


def test_a_mismatched_state_is_rejected(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)

    assert finish(client, state="some-other-state").status_code == 401
    assert credentials(sessions) == []


def test_a_state_issued_for_slack_cannot_finish_a_discord_install(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(discord_ok)
    start(client, "slack")

    assert finish(client, "discord").status_code == 401
    assert credentials(sessions) == []


def test_a_permission_revoked_mid_flow_stops_the_install(api_db):
    """The user was away at Slack while their role changed; the callback
    re-checks rather than trusting the install step."""
    client, sessions = api_db
    workspace = sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)

    with sessions() as session:
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id
            )
        )
        membership.role = Role.VIEWER
        session.commit()

    assert finish(client).status_code == 403
    assert credentials(sessions) == []


def test_a_rejected_code_says_nothing_about_which_check_failed(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(lambda r: httpx.Response(200, json={"ok": False, "error": "invalid_code"}))
    start(client)

    response = finish(client)

    assert response.status_code == 401
    assert response.json()["detail"] == "Connecting the source failed. Please try again."
    assert credentials(sessions) == []


def test_discord_without_a_server_is_not_a_connection(api_db):
    """Completing the flow without adding the bot anywhere leaves nothing to read."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(lambda r: httpx.Response(200, json={"scope": "bot"}))
    start(client, "discord")

    assert finish(client, "discord").status_code == 401
    assert credentials(sessions) == []


def test_re_authorising_replaces_the_connection(api_db):
    """A second install may have landed on a different team, so carrying the old
    external_ref over would point data_sources at a source nobody authorised."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)
    finish(client)

    other = {"id": "T0OTHER", "name": "Other"}
    fake_provider(
        lambda r: httpx.Response(
            200, json={"ok": True, "access_token": "xoxb-other", "scope": "", "team": other}
        )
    )
    start(client)
    finish(client)

    (row,) = credentials(sessions)
    assert row.external_ref == "T0OTHER"


# -- Reading and removing connections ------------------------------------------


def test_any_member_can_see_what_is_connected_without_the_token(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)
    finish(client)

    response = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/connections")

    assert response.status_code == 200
    assert response.json() == [
        {
            "kind": "slack",
            "external_ref": "T0ACME",
            "display_name": "Acme",
            "installed_by_name": "member",
            "workspace_id": TEST_WORKSPACE_ID,
        }
    ]
    assert BOT_TOKEN not in response.text


def test_disconnecting_removes_the_credential(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    fake_provider(slack_ok)
    start(client)
    finish(client)

    response = client.delete(f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/slack")

    assert response.status_code == 204
    assert credentials(sessions) == []
    with sessions() as session:
        with pytest.raises(SourceCredentialMissing):
            get_chat_credential(
                session, workspace_id=uuid.UUID(TEST_WORKSPACE_ID), kind="slack"
            )


def test_disconnecting_something_that_is_not_connected_is_a_404(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)

    response = client.delete(f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/slack")

    assert response.status_code == 404


def test_a_viewer_cannot_disconnect(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.VIEWER)

    response = client.delete(f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/slack")

    assert response.status_code == 403
