"""T-8.3 / T-8.4 integration: Slack and Discord -> real Neo4j -> graph endpoint.

Only the providers are mocked. The Cypher in `app.sources.chat_graph` runs
against the real database, which is the only way to know that the composite
uniqueness constraints hold, that re-ingesting is idempotent, and that the
string-keyed chat nodes come back out of the workspace-scoped read.

Skipped automatically when Neo4j isn't running.
"""

import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.api.sources import get_chat_client_builder
from app.config import settings
from app.main import app
from app.models import Role, SourceCredential
from app.sources.discord import DiscordClient
from app.sources.slack import SlackClient
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import TEST_WORKSPACE_ID, TEST_WORKSPACE_ID_B

pytestmark = pytest.mark.integration

TEAM = "T0ACME"
GUILD = "912340000000000000"
SLACK_CHANNELS = [{"id": "C1", "name": "decisions", "is_archived": False}]
DISCORD_CHANNELS = [{"id": "100", "name": "decisions", "type": 0}]
SLACK_USERS = [{"id": "U1", "name": "ada", "real_name": "Ada Lovelace", "profile": {}}]


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(
        settings, "token_encryption_key", SecretStr(Fernet.generate_key().decode())
    )
    monkeypatch.setattr(settings, "token_encryption_previous_keys", None)
    monkeypatch.setattr(settings, "discord_bot_token", SecretStr("discord-bot-token"))
    yield
    app.dependency_overrides.pop(get_chat_client_builder, None)


def slack_handler(messages):
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "conversations.list":
            return httpx.Response(200, json={"ok": True, "channels": SLACK_CHANNELS})
        if method == "users.list":
            return httpx.Response(200, json={"ok": True, "members": SLACK_USERS})
        if method == "conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": list(messages)})
        return httpx.Response(200, json={"ok": True, "messages": []})

    return handler


def discord_handler(messages):
    def handler(request):
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json=DISCORD_CHANNELS)
        if request.url.params.get("before") is not None:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=list(messages))

    return handler


def use_providers(slack=None, discord=None):
    def builder(kind: str, token: str):
        handler = slack if kind == "slack" else discord
        cls = SlackClient if kind == "slack" else DiscordClient
        return cls(
            token, transport=httpx.MockTransport(handler), sleep=lambda s: None
        )

    app.dependency_overrides[get_chat_client_builder] = lambda: builder


@pytest.fixture
def client(api_db):
    """A caller holding OWNER on both reserved test workspaces, with both
    providers already connected to each."""
    test_client, sessions = api_db
    with sessions() as session:
        owner = make_user(session, "chat-owner@example.com")
        for workspace_id, name in (
            (TEST_WORKSPACE_ID, "Primary"),
            (TEST_WORKSPACE_ID_B, "Secondary"),
        ):
            workspace = make_workspace(session, name, workspace_id)
            grant(session, workspace, owner, Role.OWNER)
            session.add(
                SourceCredential(
                    workspace_id=uuid.UUID(workspace_id),
                    kind="slack",
                    external_ref=TEAM,
                    display_name="Acme",
                    access_token="xoxb-test",
                    scope="",
                )
            )
            session.add(
                SourceCredential(
                    workspace_id=uuid.UUID(workspace_id),
                    kind="discord",
                    external_ref=GUILD,
                    display_name="Acme Guild",
                    access_token=None,
                    scope="",
                )
            )
        session.commit()
        session.refresh(owner)
    authenticate(test_client, sessions, owner)
    return test_client


def slack_message(ts, text="decided", **over):
    return {"ts": ts, "text": text, "user": "U1", **over}


def discord_message(mid, content="decided", **over):
    return {
        "id": mid,
        "content": content,
        "timestamp": "2026-10-31T09:00:00+00:00",
        "author": {"id": "7001", "username": "ada"},
        **over,
    }


def ingest(client, kind, channel_ids, workspace_id=TEST_WORKSPACE_ID):
    return client.post(
        f"/api/ingest/{kind}",
        json={"workspace_id": workspace_id, "channel_ids": channel_ids},
    )


def nodes_of(client, workspace_id=TEST_WORKSPACE_ID, node_type=None):
    body = client.get(f"/api/workspaces/{workspace_id}/graph").json()
    return [
        node
        for node in body["nodes"]
        if node_type is None or node["type"] == node_type
    ]


def test_slack_messages_reach_the_graph_endpoint(client, graph):
    use_providers(slack=slack_handler([slack_message("1730000000.000100")]))

    assert ingest(client, "slack", ["C1"]).status_code == 200

    messages = nodes_of(client, node_type="Message")
    (message,) = messages
    assert message["key"] == "Message:slack/C1/1730000000.000100"
    assert message["title"] == "decided"
    (channel,) = nodes_of(client, node_type="Channel")
    assert channel["title"] == "#decisions"


def test_a_message_is_linked_to_its_channel_and_author(client, graph):
    use_providers(slack=slack_handler([slack_message("1730000000.000100")]))
    ingest(client, "slack", ["C1"])

    edges = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/graph").json()["edges"]

    assert {
        "source": "Message:slack/C1/1730000000.000100",
        "target": "Channel:slack/C1",
        "type": "IN_CHANNEL",
    } in edges
    assert {
        "source": "Author:slack/U1",
        "target": "Message:slack/C1/1730000000.000100",
        "type": "POSTED",
    } in edges


def test_re_ingesting_the_same_channel_creates_no_duplicates(client, graph):
    """Every write is a MERGE on the composite key, so a second sync updates."""
    use_providers(slack=slack_handler([slack_message("1730000000.000100")]))

    ingest(client, "slack", ["C1"])
    ingest(client, "slack", ["C1"])

    assert len(nodes_of(client, node_type="Message")) == 1
    assert len(nodes_of(client, node_type="Channel")) == 1
    assert len(nodes_of(client, node_type="Author")) == 1


def test_an_edited_message_is_updated_rather_than_duplicated(client, graph):
    use_providers(slack=slack_handler([slack_message("1730000000.000100", "first")]))
    ingest(client, "slack", ["C1"])

    use_providers(slack=slack_handler([slack_message("1730000000.000100", "edited")]))
    ingest(client, "slack", ["C1"])

    (message,) = nodes_of(client, node_type="Message")
    assert message["title"] == "edited"


def test_two_workspaces_ingesting_one_slack_team_keep_separate_nodes(client, graph):
    """The same composite-key rule GitHub relies on: a provider id alone is
    deliberately not unique across workspaces."""
    use_providers(slack=slack_handler([slack_message("1730000000.000100")]))

    ingest(client, "slack", ["C1"], TEST_WORKSPACE_ID)
    ingest(client, "slack", ["C1"], TEST_WORKSPACE_ID_B)

    assert len(nodes_of(client, TEST_WORKSPACE_ID, "Message")) == 1
    assert len(nodes_of(client, TEST_WORKSPACE_ID_B, "Message")) == 1


def test_a_workspace_never_sees_another_workspaces_messages(client, graph):
    use_providers(slack=slack_handler([slack_message("1730000000.000100")]))
    ingest(client, "slack", ["C1"], TEST_WORKSPACE_ID)

    assert nodes_of(client, TEST_WORKSPACE_ID_B) == []


def test_a_slack_thread_reply_is_linked_to_its_parent(client, graph):
    parent = slack_message("1730000000.000100", "question", reply_count=1, thread_ts="1730000000.000100")

    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "conversations.list":
            return httpx.Response(200, json={"ok": True, "channels": SLACK_CHANNELS})
        if method == "users.list":
            return httpx.Response(200, json={"ok": True, "members": SLACK_USERS})
        if method == "conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": [parent]})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    parent,
                    slack_message("1730000001.000200", "answer", thread_ts="1730000000.000100"),
                ],
            },
        )

    use_providers(slack=handler)
    ingest(client, "slack", ["C1"])

    edges = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/graph").json()["edges"]
    assert {
        "source": "Message:slack/C1/1730000001.000200",
        "target": "Message:slack/C1/1730000000.000100",
        "type": "REPLY_TO",
    } in edges


def test_discord_messages_reach_the_graph_endpoint(client, graph):
    use_providers(discord=discord_handler([discord_message("900")]))

    assert ingest(client, "discord", ["100"]).status_code == 200

    (message,) = nodes_of(client, node_type="Message")
    assert message["key"] == "Message:discord/100/900"
    # A Discord author id is numeric; the prefix is what keeps it from being
    # read as an integer GitHub id.
    (author,) = nodes_of(client, node_type="Author")
    assert author["key"] == "Author:discord/7001"


def test_slack_and_discord_coexist_in_one_workspace(client, graph):
    use_providers(
        slack=slack_handler([slack_message("1730000000.000100")]),
        discord=discord_handler([discord_message("900")]),
    )

    ingest(client, "slack", ["C1"])
    ingest(client, "discord", ["100"])

    keys = {node["key"] for node in nodes_of(client, node_type="Message")}
    assert keys == {
        "Message:slack/C1/1730000000.000100",
        "Message:discord/100/900",
    }


def test_the_sources_page_counts_each_connection_separately(client, graph):
    use_providers(
        slack=slack_handler(
            [slack_message("1730000000.000100"), slack_message("1730000000.000200")]
        ),
        discord=discord_handler([discord_message("900")]),
    )
    ingest(client, "slack", ["C1"])
    ingest(client, "discord", ["100"])

    rows = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()

    by_kind = {row["kind"]: row for row in rows}
    assert (by_kind["slack"]["channels"], by_kind["slack"]["messages"]) == (1, 2)
    assert (by_kind["discord"]["channels"], by_kind["discord"]["messages"]) == (1, 1)


def test_a_message_detail_read_offers_the_original_link(client, graph):
    """US-08 AC4, end to end against the real database."""
    use_providers(slack=slack_handler([slack_message("1730000000.000100")]))
    ingest(client, "slack", ["C1"])

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}"
        "/graph/nodes/Message/slack/C1/1730000000.000100"
    )

    assert response.status_code == 200
    # Its own link first, then its channel's: the inspector lists provenance for
    # the node and the nodes it is attached to.
    origins = response.json()["origins"]
    assert origins[0]["type"] == "Message"
    assert origins[0]["url"] == (
        "https://slack.com/app_redirect?channel=C1&message_ts=1730000000.000100"
    )
    assert "Channel" in {origin["type"] for origin in origins}
