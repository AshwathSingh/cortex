"""T-8.3 / T-8.4: writing chat messages into the workspace graph.

Nodes:  (:Channel {id, workspace_id}), (:Message {id, workspace_id}),
        (:Author {id, workspace_id})
Edges:  (:Author)-[:POSTED]->(:Message)
        (:Message)-[:IN_CHANNEL]->(:Channel)
        (:Message)-[:REPLY_TO]->(:Message)

Slack and Discord both land here. They disagree about almost everything in their
payloads, so each adapter validates its own JSON and normalises it into the
dataclasses below; this module only knows the normalised form. That keeps one
copy of the MERGE ordering, the workspace scoping and the idempotency.

Ids are provider-prefixed -- ``slack/C0ABC``, ``discord/912…`` -- and that is
load-bearing, not decoration:

* ``Author`` is shared with GitHub, whose ids are *integers* in the graph. A
  Discord user id is a numeric string, so without the prefix
  ``Author:912340000000000000`` could not be told apart from a GitHub id and the
  canvas would try to match an int against a string.
* A Slack message timestamp is unique only *within a channel*, so a message id
  carries its channel: ``slack/C0ABC/1730000000.123456``.
* ``app.graph.queries`` recovers the type from the key by trying ``int()`` first.
  Every prefixed id contains a ``/``, so that attempt always fails for chat and
  always succeeds for GitHub.

Every node carries ``source_ref`` -- the Slack team id or Discord guild id that
``data_sources`` keys on -- so the Sources page can count what each connection
contributed without a second lookup table.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from neo4j import Driver

from app.github.mapper import normalise_workspace_id

Statement = tuple[str, dict[str, Any]]


def qualify(kind: str, *parts: str) -> str:
    """The graph id for a provider-native id. See the module docstring."""
    return "/".join((kind, *parts))


@dataclass(frozen=True)
class ChatAuthor:
    id: str
    login: str
    url: str | None = None


@dataclass(frozen=True)
class ChatChannel:
    id: str
    name: str
    url: str | None = None


@dataclass(frozen=True)
class ChatMessage:
    id: str
    channel_id: str
    body: str
    #: Provenance link back to the message in Slack or Discord (US-08 AC4).
    url: str
    created_at: str  # ISO-8601
    author_id: str | None = None
    #: The thread parent, for a reply. None for a top-level message.
    reply_to_id: str | None = None


UPSERT_AUTHORS = """
UNWIND $rows AS row
MERGE (a:Author {id: row.id, workspace_id: $workspace_id})
SET a.login = row.login, a.html_url = row.url, a.kind = $kind,
    a.source_ref = $source_ref
"""

UPSERT_CHANNELS = """
UNWIND $rows AS row
MERGE (c:Channel {id: row.id, workspace_id: $workspace_id})
SET c.name = row.name, c.html_url = row.url, c.kind = $kind,
    c.source_ref = $source_ref
"""

UPSERT_MESSAGES = """
UNWIND $rows AS row
MERGE (m:Message {id: row.id, workspace_id: $workspace_id})
SET m += row.props
WITH m, row
MATCH (c:Channel {id: row.channel_id, workspace_id: $workspace_id})
MERGE (m)-[:IN_CHANNEL]->(c)
"""

LINK_AUTHORS = """
UNWIND $rows AS row
MATCH (m:Message {id: row.message_id, workspace_id: $workspace_id})
MATCH (a:Author {id: row.author_id, workspace_id: $workspace_id})
MERGE (a)-[:POSTED]->(m)
"""

# Replies are linked last: the parent may be later in the same batch, so both
# ends only certainly exist once every message has been merged.
LINK_REPLIES = """
UNWIND $rows AS row
MATCH (m:Message {id: row.message_id, workspace_id: $workspace_id})
MATCH (parent:Message {id: row.reply_to_id, workspace_id: $workspace_id})
MERGE (m)-[:REPLY_TO]->(parent)
"""


def build_statements(
    *,
    workspace_id: str | uuid.UUID,
    kind: str,
    source_ref: str,
    channels: Iterable[ChatChannel],
    authors: Iterable[ChatAuthor],
    messages: Iterable[ChatMessage],
) -> list[Statement]:
    """Ordered (cypher, params) pairs. Channels and authors first, so the
    message edges have something to MATCH."""
    workspace = normalise_workspace_id(workspace_id)
    scope = {"workspace_id": workspace, "kind": kind, "source_ref": source_ref}

    channel_rows = [
        {"id": c.id, "name": c.name, "url": c.url} for c in channels
    ]
    author_rows = [
        {"id": a.id, "login": a.login, "url": a.url} for a in authors
    ]
    message_list = list(messages)
    known_channels = {row["id"] for row in channel_rows}
    known_messages = {m.id for m in message_list}

    message_rows = []
    author_links = []
    reply_links = []
    for message in message_list:
        # A message whose channel was not fetched would MATCH nothing and be
        # written with no edge; drop it instead of orphaning it on the canvas.
        if message.channel_id not in known_channels:
            continue
        message_rows.append(
            {
                "id": message.id,
                "channel_id": message.channel_id,
                "props": {
                    "id": message.id,
                    "body": message.body,
                    "html_url": message.url,
                    "created_at": message.created_at,
                    "channel_id": message.channel_id,
                    "kind": kind,
                    "source_ref": source_ref,
                    "workspace_id": workspace,
                },
            }
        )
        if message.author_id is not None:
            author_links.append(
                {"message_id": message.id, "author_id": message.author_id}
            )
        # Only inside this batch: a parent in an older sync is already in the
        # graph, but one that was never fetched would MATCH nothing and silently
        # drop the whole row's edge.
        if message.reply_to_id is not None and message.reply_to_id in known_messages:
            reply_links.append(
                {"message_id": message.id, "reply_to_id": message.reply_to_id}
            )

    statements: list[Statement] = []
    if channel_rows:
        statements.append((UPSERT_CHANNELS, {"rows": channel_rows, **scope}))
    if author_rows:
        statements.append((UPSERT_AUTHORS, {"rows": author_rows, **scope}))
    if message_rows:
        statements.append((UPSERT_MESSAGES, {"rows": message_rows, **scope}))
    if author_links:
        statements.append(
            (LINK_AUTHORS, {"rows": author_links, "workspace_id": workspace})
        )
    if reply_links:
        statements.append(
            (LINK_REPLIES, {"rows": reply_links, "workspace_id": workspace})
        )
    return statements


def write_chat_graph(
    driver: Driver,
    *,
    workspace_id: str | uuid.UUID,
    kind: str,
    source_ref: str,
    channels: Iterable[ChatChannel],
    authors: Iterable[ChatAuthor],
    messages: Iterable[ChatMessage],
) -> int:
    """Write everything in one transaction. Returns statements run.

    All-or-nothing, like US-7's ``write_graph``: a partial chat ingestion would
    leave messages with no channel to hang off.
    """
    statements = build_statements(
        workspace_id=workspace_id,
        kind=kind,
        source_ref=source_ref,
        channels=channels,
        authors=authors,
        messages=messages,
    )

    def work(tx):
        for cypher, params in statements:
            tx.run(cypher, **params)

    with driver.session() as session:
        session.execute_write(work)
    return len(statements)
