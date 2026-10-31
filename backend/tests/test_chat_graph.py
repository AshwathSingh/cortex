"""T-8.3 / T-8.4: turning normalised chat messages into Cypher.

Slack and Discord share this mapper, so what is pinned here is the ordering and
the guards -- the things that decide whether an edge binds to anything at all.
"""

import pytest

from app.sources.chat_graph import (
    LINK_AUTHORS,
    LINK_REPLIES,
    UPSERT_AUTHORS,
    UPSERT_CHANNELS,
    UPSERT_MESSAGES,
    ChatAuthor,
    ChatChannel,
    ChatMessage,
    build_statements,
    qualify,
    write_chat_graph,
)

WS = "ccccccc0-0000-4000-8000-00000000c0de"
CHANNEL = ChatChannel(id="slack/C1", name="general", url="https://slack/c1")
AUTHOR = ChatAuthor(id="slack/U1", login="ada")


def message(ts="1.1", **over) -> ChatMessage:
    defaults = {
        "id": f"slack/C1/{ts}",
        "channel_id": "slack/C1",
        "body": "hello",
        "url": f"https://slack/{ts}",
        "created_at": "2026-10-31T00:00:00+00:00",
        "author_id": "slack/U1",
    }
    return ChatMessage(**{**defaults, **over})


def build(**over):
    defaults = {
        "workspace_id": WS,
        "kind": "slack",
        "source_ref": "T0ACME",
        "channels": [CHANNEL],
        "authors": [AUTHOR],
        "messages": [message()],
    }
    return build_statements(**{**defaults, **over})


def queries(statements) -> list[str]:
    return [cypher for cypher, _ in statements]


def params_for(statements, query) -> dict:
    return next(params for cypher, params in statements if cypher is query)


def test_qualify_prefixes_the_provider():
    assert qualify("slack", "U1") == "slack/U1"
    assert qualify("discord", "C1", "99") == "discord/C1/99"


def test_channels_and_authors_are_written_before_messages_and_edges():
    """The message edges MATCH both ends, so a later channel would bind nothing."""
    assert queries(build()) == [
        UPSERT_CHANNELS,
        UPSERT_AUTHORS,
        UPSERT_MESSAGES,
        LINK_AUTHORS,
    ]


def test_every_node_carries_the_workspace_and_its_source():
    statements = build()
    for query in (UPSERT_CHANNELS, UPSERT_AUTHORS, UPSERT_MESSAGES):
        params = params_for(statements, query)
        assert params["workspace_id"] == WS
        assert params["source_ref"] == "T0ACME"
        assert params["kind"] == "slack"
    props = params_for(statements, UPSERT_MESSAGES)["rows"][0]["props"]
    assert props["workspace_id"] == WS
    assert props["source_ref"] == "T0ACME"


def test_a_message_keeps_its_provenance_link():
    props = params_for(build(), UPSERT_MESSAGES)["rows"][0]["props"]
    assert props["html_url"] == "https://slack/1.1"


def test_a_message_whose_channel_was_not_fetched_is_dropped():
    """It would MATCH no channel and land on the canvas with no edge at all."""
    statements = build(messages=[message(channel_id="slack/CELSEWHERE")])

    assert UPSERT_MESSAGES not in queries(statements)
    assert LINK_AUTHORS not in queries(statements)


def test_an_authorless_message_is_still_written():
    statements = build(messages=[message(author_id=None)], authors=[])

    assert UPSERT_MESSAGES in queries(statements)
    assert LINK_AUTHORS not in queries(statements)


def test_a_reply_is_linked_to_its_parent():
    parent = message("1.1")
    reply = message("2.2", reply_to_id=parent.id)

    statements = build(messages=[parent, reply])

    assert queries(statements)[-1] is LINK_REPLIES
    assert params_for(statements, LINK_REPLIES)["rows"] == [
        {"message_id": "slack/C1/2.2", "reply_to_id": "slack/C1/1.1"}
    ]


def test_a_reply_whose_parent_is_outside_the_batch_is_not_linked():
    """The parent may be in an older sync, but one that was never fetched would
    MATCH nothing and drop the row's edge silently."""
    statements = build(messages=[message("2.2", reply_to_id="slack/C1/0.0")])

    assert LINK_REPLIES not in queries(statements)
    assert UPSERT_MESSAGES in queries(statements)


def test_nothing_is_written_for_an_empty_fetch():
    assert build(channels=[], authors=[], messages=[]) == []


def test_a_missing_workspace_is_refused_before_any_statement_is_built():
    with pytest.raises(ValueError, match="workspace_id"):
        build(workspace_id=None)


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **params):
        self.calls.append(cypher)


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_write(self, fn):
        fn(self.tx)


class FakeDriver:
    def __init__(self):
        self.tx = FakeTx()
        self.sessions = 0

    def session(self):
        self.sessions += 1
        return FakeSession(self.tx)


def test_everything_is_written_in_one_transaction():
    """A partial chat ingestion would leave messages with no channel to hang off."""
    driver = FakeDriver()

    count = write_chat_graph(
        driver,
        workspace_id=WS,
        kind="slack",
        source_ref="T0ACME",
        channels=[CHANNEL],
        authors=[AUTHOR],
        messages=[message()],
    )

    assert driver.sessions == 1
    assert count == len(driver.tx.calls) == 4
