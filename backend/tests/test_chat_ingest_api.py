"""T-8.3 / T-8.4 endpoint behaviour, and US-08 AC3.

The relational half is real (in-memory) so authorisation genuinely runs; the
providers and Neo4j are faked. The acceptance criterion these build up to is
AC3: a workspace with a GitHub repository, a Slack team and a Discord server
lists all three together, each with its own sync status.
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.api.graph import get_neo4j as graph_neo4j
from app.api.ingest import get_neo4j as ingest_neo4j
from app.api.sources import get_chat_client_builder
from app.config import settings
from app.main import app
from app.models import (
    DataSource,
    Role,
    SourceCredential,
    SyncStatus,
)
from app.sources.discord import DiscordClient
from app.sources.slack import SlackClient
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID
from tests.test_ingest_api import FakeDriver
from tests.test_source_queries import SourceDriver

TEAM = "T0ACME"
GUILD = "912340000000000000"
SLACK_CHANNELS = [{"id": "C1", "name": "general", "is_archived": False}]
DISCORD_CHANNELS = [{"id": "100", "name": "general", "type": 0}]


ATTEMPTED_AT = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """A Slack token has to be encryptable to be stored, and Discord reads with
    the application-wide bot token rather than one from the row."""
    monkeypatch.setattr(
        settings, "token_encryption_key", SecretStr(Fernet.generate_key().decode())
    )
    monkeypatch.setattr(settings, "token_encryption_previous_keys", None)
    monkeypatch.setattr(settings, "discord_bot_token", SecretStr("discord-bot-token"))
    yield
    for dependency in (ingest_neo4j, graph_neo4j, get_chat_client_builder):
        app.dependency_overrides.pop(dependency, None)


def connect(sessions, kind, external_ref, display_name):
    """Give the workspace a connection without going through the OAuth flow."""
    with sessions() as session:
        session.add(
            SourceCredential(
                workspace_id=uuid.UUID(TEST_WORKSPACE_ID),
                kind=kind,
                external_ref=external_ref,
                display_name=display_name,
                # Slack needs a stored token; Discord reads from config.
                access_token="xoxb-test" if kind == "slack" else None,
                scope="",
            )
        )
        session.commit()


def slack_handler(messages=()):
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "conversations.list":
            return httpx.Response(200, json={"ok": True, "channels": SLACK_CHANNELS})
        if method == "users.list":
            return httpx.Response(200, json={"ok": True, "members": []})
        if method == "conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": list(messages)})
        return httpx.Response(200, json={"ok": True, "messages": []})

    return handler


def discord_handler(messages=()):
    def handler(request):
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json=DISCORD_CHANNELS)
        if request.url.params.get("before") is not None:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=list(messages))

    return handler


def fake_clients(slack=None, discord=None):
    def builder(kind: str, token: str):
        handler = slack if kind == "slack" else discord
        assert handler is not None, f"no fake configured for {kind}"
        cls = SlackClient if kind == "slack" else DiscordClient
        return cls(
            token, transport=httpx.MockTransport(handler), sleep=lambda s: None
        )

    app.dependency_overrides[get_chat_client_builder] = lambda: builder


def setup(api_db, *, role=Role.OWNER, driver=None):
    client, sessions = api_db
    driver = driver or FakeDriver()
    app.dependency_overrides[ingest_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


def sources(sessions) -> list[DataSource]:
    with sessions() as session:
        return list(
            session.scalars(
                select(DataSource).order_by(DataSource.kind, DataSource.external_ref)
            )
        )


# -- Picking channels ----------------------------------------------------------


def test_slack_channels_are_listed_for_the_picker(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")
    fake_clients(slack=slack_handler())

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/slack/channels"
    )

    assert response.status_code == 200
    assert response.json() == [{"id": "C1", "name": "general"}]


def test_discord_channels_are_listed_for_the_picker(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    connect(sessions, "discord", GUILD, "Acme Guild")
    fake_clients(discord=discord_handler())

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/discord/channels"
    )

    assert response.status_code == 200
    assert response.json() == [{"id": "100", "name": "general"}]


def test_listing_channels_needs_sources_write(api_db):
    """It spends the provider's rate limit and discloses private channel names."""
    client, _ = setup(api_db, role=Role.VIEWER)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/slack/channels"
    )

    assert response.status_code == 403
    assert "sources.write" in response.json()["detail"]


def test_listing_channels_without_a_connection_says_to_connect_one(api_db):
    client, _ = setup(api_db)

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/connections/slack/channels"
    )

    assert response.status_code == 409
    assert "Authorise Slack first" in response.json()["detail"]


# -- Ingesting -----------------------------------------------------------------


def body(**over) -> dict:
    return {"workspace_id": TEST_WORKSPACE_ID, "channel_ids": ["C1"], **over}


def test_slack_ingestion_writes_the_graph_and_records_the_source(api_db):
    client, driver = setup(api_db)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")
    fake_clients(slack=slack_handler([{"ts": "1.1", "text": "hi", "user": "U1"}]))

    response = client.post("/api/ingest/slack", json=body())

    assert response.status_code == 200
    assert response.json() == {"source": "Acme", "channels": 1, "messages": 1}
    assert driver.tx.calls  # the graph really was written
    (source,) = sources(sessions)
    assert (source.kind, source.external_ref) == ("slack", TEAM)
    assert source.status is SyncStatus.SUCCESS
    assert source.last_synced_at is not None


def test_discord_ingestion_writes_the_graph_and_records_the_source(api_db):
    client, driver = setup(api_db)
    _, sessions = api_db
    connect(sessions, "discord", GUILD, "Acme Guild")
    fake_clients(
        discord=discord_handler(
            [
                {
                    "id": "900",
                    "content": "hi",
                    "timestamp": "2026-10-31T09:00:00+00:00",
                    "author": {"id": "7001", "username": "ada"},
                }
            ]
        )
    )

    response = client.post("/api/ingest/discord", json=body(channel_ids=["100"]))

    assert response.status_code == 200
    assert response.json() == {"source": "Acme Guild", "channels": 1, "messages": 1}
    (source,) = sources(sessions)
    assert (source.kind, source.external_ref) == ("discord", GUILD)


def test_ingesting_without_a_connection_is_a_409(api_db):
    client, driver = setup(api_db)

    response = client.post("/api/ingest/slack", json=body())

    assert response.status_code == 409
    assert driver.sessions == 0


def test_a_viewer_cannot_ingest_chat(api_db):
    client, driver = setup(api_db, role=Role.VIEWER)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")

    response = client.post("/api/ingest/slack", json=body())

    assert response.status_code == 403
    assert driver.sessions == 0
    # Authorisation runs before any provider call, so nothing was read either.
    assert sources(sessions) == []


def test_an_anonymous_caller_cannot_ingest_chat(api_db):
    client, driver = setup(api_db, role=None)

    assert client.post("/api/ingest/slack", json=body()).status_code == 401
    assert driver.sessions == 0


def test_at_least_one_channel_must_be_chosen(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")

    assert client.post("/api/ingest/slack", json=body(channel_ids=[])).status_code == 422


def test_a_provider_failure_is_recorded_against_the_source(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")
    fake_clients(
        slack=lambda r: httpx.Response(200, json={"ok": False, "error": "token_revoked"})
    )

    response = client.post("/api/ingest/slack", json=body())

    assert response.status_code == 403
    assert "Reconnect the Slack workspace" in response.json()["detail"]
    (source,) = sources(sessions)
    assert source.status is SyncStatus.FAILED
    assert "Reconnect the Slack workspace" in source.last_error


def test_a_second_ingestion_of_the_same_team_is_refused_while_one_runs(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    connect(sessions, "slack", TEAM, "Acme")
    fake_clients(slack=slack_handler())
    client.post("/api/ingest/slack", json=body())

    # Re-run the lease by hand: the first call finished, so take it again.
    from app.services.data_sources import record_sync_attempt

    with sessions() as session:
        record_sync_attempt(
            session,
            workspace_id=uuid.UUID(TEST_WORKSPACE_ID),
            external_ref=TEAM,
            kind="slack",
        )
        session.commit()

    response = client.post("/api/ingest/slack", json=body())

    assert response.status_code == 409
    assert TEAM in response.json()["detail"]


# -- US-08 AC3 -----------------------------------------------------------------


def test_github_slack_and_discord_appear_together_on_the_sources_page(api_db):
    """AC3: all three listed, each with its own sync status and last-synced time."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    app.dependency_overrides[graph_neo4j] = lambda: SourceDriver(
        records=[
            {
                "repo": "acme/widgets",
                "pull_requests": 4,
                "issues": 1,
                "total_items": 5,
            }
        ],
        chat_records=[
            {"source_ref": TEAM, "channels": 2, "messages": 30, "kind": "slack"},
            {"source_ref": GUILD, "channels": 1, "messages": 7, "kind": "discord"},
        ],
    )
    with sessions() as session:
        for kind, ref, status in (
            ("github", "acme/widgets", SyncStatus.SUCCESS),
            ("slack", TEAM, SyncStatus.SUCCESS),
            ("discord", GUILD, SyncStatus.FAILED),
        ):
            session.add(
                DataSource(
                    workspace_id=uuid.UUID(TEST_WORKSPACE_ID),
                    kind=kind,
                    external_ref=ref,
                    status=status,
                    last_attempted_at=ATTEMPTED_AT,
                    last_error="bot was removed" if status is SyncStatus.FAILED else None,
                )
            )
        session.commit()

    rows = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()

    by_kind = {row["kind"]: row for row in rows}
    assert set(by_kind) == {"github", "slack", "discord"}
    assert by_kind["github"]["pull_requests"] == 4
    assert (by_kind["slack"]["channels"], by_kind["slack"]["messages"]) == (2, 30)
    assert by_kind["slack"]["total_items"] == 32
    assert by_kind["discord"]["status"] == "FAILED"
    assert by_kind["discord"]["last_error"] == "bot was removed"
