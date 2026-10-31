"""US-08 AC4, and the node-id widening T-8.5 needed.

GitHub ids are integers in the graph and chat ids are provider-prefixed strings,
but a node key and a URL path are text either way. Neo4j will not match 42
against "42", so the type has to be recovered -- and a chat id contains slashes,
which a plain path parameter would split across route segments. Both are easy to
break silently, which is what these pin.
"""

import pytest
from urllib.parse import quote

from app.api.graph import get_neo4j
from app.graph.queries import (
    GRAPH_LABELS,
    coerce_node_id,
    fetch_edge_details,
    fetch_node_details,
)
from app.main import app
from app.models import Role
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID
from tests.test_graph_details import Driver

MESSAGE_ID = "slack/C0ABC/1730000000.000100"
MESSAGE = {
    "labels": ["Message"],
    "props": {
        "id": MESSAGE_ID,
        "body": "We are going with Postgres for the relational half.",
        "html_url": "https://slack.com/app_redirect?channel=C0ABC&message_ts=1730000000.000100",
        "created_at": "2024-10-27T03:33:20+00:00",
        "channel_id": "slack/C0ABC",
        "kind": "slack",
        "source_ref": "T0ACME",
        "workspace_id": TEST_WORKSPACE_ID,
    },
}
CHANNEL = {
    "labels": ["Channel"],
    "props": {
        "id": "slack/C0ABC",
        "name": "decisions",
        "html_url": "https://slack.com/app_redirect?channel=C0ABC",
        "workspace_id": TEST_WORKSPACE_ID,
    },
}


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.pop(get_neo4j, None)


def test_chat_labels_are_drawable():
    assert "Channel" in GRAPH_LABELS
    assert "Message" in GRAPH_LABELS


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("42", 42),
        ("0", 0),
        # Every chat id contains a "/", so int() always fails for one.
        ("slack/U1", "slack/U1"),
        ("slack/C0ABC/1730000000.000100", "slack/C0ABC/1730000000.000100"),
        # A Discord snowflake is numeric; without the prefix this would coerce
        # to an int and never match the string stored in the graph.
        ("discord/912340000000000000", "discord/912340000000000000"),
    ],
)
def test_node_ids_recover_their_type_from_text(raw, expected):
    assert coerce_node_id(raw) == expected


def test_a_message_is_fetched_by_its_string_id():
    driver = Driver(
        {"labels": MESSAGE["labels"], "props": MESSAGE["props"], "connected": []}
    )

    payload = fetch_node_details(driver, TEST_WORKSPACE_ID, "Message", MESSAGE_ID)

    _, params = driver.tx.calls[0]
    # Passed through as a string, not coerced to a number.
    assert params["node_id"] == MESSAGE_ID
    assert payload["key"] == f"Message:{MESSAGE_ID}"


def test_a_message_titles_itself_from_its_opening_words():
    """A message has no title of its own, and "(no text)" beats a blank node."""
    driver = Driver(
        {"labels": MESSAGE["labels"], "props": MESSAGE["props"], "connected": []}
    )

    payload = fetch_node_details(driver, TEST_WORKSPACE_ID, "Message", MESSAGE_ID)

    assert payload["title"] == "We are going with Postgres for the relational half."
    assert payload["content"] == MESSAGE["props"]["body"]


def test_a_long_message_title_is_truncated():
    props = {**MESSAGE["props"], "body": "word " * 60}
    driver = Driver({"labels": ["Message"], "props": props, "connected": []})

    title = fetch_node_details(driver, TEST_WORKSPACE_ID, "Message", MESSAGE_ID)["title"]

    assert len(title) <= 80
    assert title.endswith("…")


def test_an_empty_message_still_has_a_label():
    props = {**MESSAGE["props"], "body": ""}
    driver = Driver({"labels": ["Message"], "props": props, "connected": []})

    payload = fetch_node_details(driver, TEST_WORKSPACE_ID, "Message", MESSAGE_ID)

    assert payload["title"] == "(no text)"


def test_a_channel_is_titled_with_a_hash():
    driver = Driver(
        {"labels": CHANNEL["labels"], "props": CHANNEL["props"], "connected": []}
    )

    payload = fetch_node_details(driver, TEST_WORKSPACE_ID, "Channel", "slack/C0ABC")

    assert payload["title"] == "#decisions"


def test_a_message_offers_the_original_as_provenance(api_db):
    """US-08 AC4: selecting a message and opening its details shows a link that
    opens it in Slack or Discord."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.VIEWER)
    app.dependency_overrides[get_neo4j] = lambda: Driver(
        {"labels": MESSAGE["labels"], "props": MESSAGE["props"], "connected": []}
    )

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/nodes/Message/{MESSAGE_ID}"
    )

    assert response.status_code == 200
    (origin,) = response.json()["origins"]
    assert origin["url"] == MESSAGE["props"]["html_url"]
    assert origin["type"] == "Message"


def test_a_percent_encoded_chat_id_reaches_the_handler_intact(api_db):
    """The frontend encodeURIComponent()s the id, so its slashes arrive as %2F.
    The route's `:path` converter is what reassembles them."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.VIEWER)
    driver = Driver(
        {"labels": MESSAGE["labels"], "props": MESSAGE["props"], "connected": []}
    )
    app.dependency_overrides[get_neo4j] = lambda: driver

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/nodes/Message/"
        f"{quote(MESSAGE_ID, safe='')}"
    )

    assert response.status_code == 200
    _, params = driver.tx.calls[0]
    assert params["node_id"] == MESSAGE_ID


def test_an_edge_between_two_chat_nodes_resolves_both_keys():
    driver = Driver(
        {
            "source_labels": MESSAGE["labels"],
            "source_props": MESSAGE["props"],
            "target_labels": CHANNEL["labels"],
            "target_props": CHANNEL["props"],
            "type": "IN_CHANNEL",
            "props": {},
        }
    )

    payload = fetch_edge_details(
        driver,
        TEST_WORKSPACE_ID,
        f"Message:{MESSAGE_ID}",
        "Channel:slack/C0ABC",
        "IN_CHANNEL",
    )

    _, params = driver.tx.calls[0]
    assert params["source_id"] == MESSAGE_ID
    assert params["target_id"] == "slack/C0ABC"
    assert payload["title"] == "In Channel"


def test_a_key_with_no_id_is_rejected():
    with pytest.raises(ValueError):
        fetch_edge_details(Driver(), TEST_WORKSPACE_ID, "Message:", "Channel:x", "X")
