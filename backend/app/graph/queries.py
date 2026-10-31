"""T-14.2: workspace-scoped Cypher for the Graph Explorer's bulk fetch.

One read per request: every node in the workspace, then every edge whose *both*
endpoints are in that workspace. Nodes with no edges are included -- an Issue
whose author was deleted still belongs on the canvas.

Scoping is `n.workspace_id = $workspace_id` and nothing else. Nodes carry the
workspace as a property (see `app.db.schema`), so a single equality predicate is
the whole boundary; there is no Workspace node to traverse from.

`workspace_id` is normalised with the *same* function the writer uses
(`app.github.mapper.normalise_workspace_id`). That is deliberate: if read and
write disagreed on the canonical form of a UUID, filtering would silently return
nothing. Do not reimplement it here.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from neo4j import Driver

from app.github.mapper import normalise_workspace_id

# The labels the Graph Explorer knows how to draw. Interpolated into Cypher
# below, which is safe *only* because this is a module constant -- never accept a
# label from a request (see the neo4j_function.py caveat in CLAUDE.md).
GRAPH_LABELS: tuple[str, ...] = (
    "Author",
    "PullRequest",
    "Issue",
    # US-08. Channel and Message ids are provider-prefixed strings rather than
    # integers; see ``coerce_node_id`` and ``app.sources.chat_graph``.
    "Channel",
    "Message",
)

# Ceilings so one enormous workspace cannot stall the browser or the API. The
# response reports whether either was hit.
DEFAULT_NODE_LIMIT = 2_000
DEFAULT_EDGE_LIMIT = 6_000
DEFAULT_ORIGIN_LIMIT = 100


def _label_predicate(variable: str) -> str:
    return " OR ".join(f"{variable}:{label}" for label in GRAPH_LABELS)


# Both queries ORDER BY before LIMIT. Without it the limit slices an arbitrary
# subset, so two requests against an unchanged workspace could return different
# nodes and the canvas would reshuffle on reload for no reason.
NODES_QUERY = f"""
MATCH (n)
WHERE ({_label_predicate("n")}) AND n.workspace_id = $workspace_id
RETURN labels(n) AS labels, properties(n) AS props
ORDER BY head(labels(n)), n.id
LIMIT $limit
"""

EDGES_QUERY = f"""
MATCH (a)-[r]->(b)
WHERE ({_label_predicate("a")}) AND ({_label_predicate("b")})
  AND a.workspace_id = $workspace_id AND b.workspace_id = $workspace_id
RETURN labels(a) AS source_labels, a.id AS source_id,
       labels(b) AS target_labels, b.id AS target_id,
       type(r) AS type
ORDER BY head(labels(a)), a.id, head(labels(b)), b.id, type(r)
LIMIT $limit
"""

NODE_DETAILS_QUERY = f"""
MATCH (n)
WHERE ({_label_predicate("n")})
  AND $node_type IN labels(n) AND n.id = $node_id
  AND n.workspace_id = $workspace_id
OPTIONAL MATCH (n)-[r]-(related)
WHERE ({_label_predicate("related")})
  AND related.workspace_id = $workspace_id
WITH n, r, related
ORDER BY head(labels(related)), related.id, type(r)
LIMIT $origin_limit
WITH n, collect(CASE WHEN r IS NULL THEN null ELSE {{
  labels: labels(related),
  props: {{id: related.id, login: related.login, number: related.number,
          title: related.title, html_url: related.html_url,
          name: related.name, body: related.body}},
  relationship: type(r),
  direction: CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END
}} END) AS connected
RETURN labels(n) AS labels, properties(n) AS props, connected
"""

EDGE_DETAILS_QUERY = f"""
MATCH (source)-[r]->(target)
WHERE ({_label_predicate("source")}) AND ({_label_predicate("target")})
  AND $source_type IN labels(source) AND source.id = $source_id
  AND $target_type IN labels(target) AND target.id = $target_id
  AND source.workspace_id = $workspace_id
  AND target.workspace_id = $workspace_id
  AND type(r) = $edge_type
RETURN labels(source) AS source_labels, properties(source) AS source_props,
       labels(target) AS target_labels, properties(target) AS target_props,
       type(r) AS type, properties(r) AS props
ORDER BY type(r)
LIMIT 1
"""

SOURCES_QUERY = """
MATCH (source)
WHERE (source:Repository OR source:PullRequest OR source:Issue)
  AND source.workspace_id = $workspace_id
  AND source.repo IS NOT NULL
WITH DISTINCT source.repo AS repo
OPTIONAL MATCH (n)
WHERE (n:PullRequest OR n:Issue)
  AND n.workspace_id = $workspace_id
  AND n.repo = repo
RETURN repo,
       sum(CASE WHEN n:PullRequest THEN 1 ELSE 0 END) AS pull_requests,
       sum(CASE WHEN n:Issue THEN 1 ELSE 0 END) AS issues,
       count(n) AS total_items
ORDER BY toLower(repo), repo
"""


# Chat sources are counted separately from repositories: they group on
# ``source_ref`` (the Slack team or Discord guild that ``data_sources`` keys on)
# rather than on ``repo``, and a channel is itself an indexed item.
CHAT_SOURCES_QUERY = """
MATCH (c:Channel)
WHERE c.workspace_id = $workspace_id AND c.source_ref IS NOT NULL
WITH DISTINCT c.source_ref AS source_ref
OPTIONAL MATCH (channel:Channel)
WHERE channel.workspace_id = $workspace_id
  AND channel.source_ref = source_ref
WITH source_ref, count(DISTINCT channel) AS channels,
     head(collect(channel.kind)) AS kind
OPTIONAL MATCH (message:Message)
WHERE message.workspace_id = $workspace_id
  AND message.source_ref = source_ref
RETURN source_ref, channels, kind, count(DISTINCT message) AS messages
ORDER BY source_ref
"""


@dataclass
class GraphPayload:
    """What the endpoint serialises. Keys are stable; the frontend builds on them."""

    workspace_id: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class SourceSummaryPayload:
    """Indexed graph items for one connected source.

    ``repo`` is the source's reference -- ``owner/name`` for GitHub, the Slack
    team id or Discord guild id for a chat source. The field name predates US-08
    and the Sources page builds on it, so it stays.
    """

    repo: str
    pull_requests: int = 0
    issues: int = 0
    total_items: int = 0
    channels: int = 0
    messages: int = 0
    #: The provider the nodes were written by, for a chat source. None for a
    #: repository, whose nodes predate the property.
    kind: str | None = None


def node_key(labels: list[str] | tuple[str, ...], node_id: Any) -> str:
    """Stable per-node identity for the client: ``"PullRequest:42"``.

    A GitHub id is only unique *within* a label -- an Author id and an Issue id
    are different numbering spaces and can collide numerically -- so the raw id
    alone is not safe as a canvas key.
    """
    return f"{_primary_label(labels)}:{node_id}"


def _primary_label(labels: list[str] | tuple[str, ...]) -> str:
    for label in labels:
        if label in GRAPH_LABELS:
            return label
    # Only reachable if a node gained a label outside GRAPH_LABELS; keep it
    # addressable rather than dropping it silently.
    return labels[0] if labels else "Unknown"


#: A message has no title of its own, so the canvas label is its opening words.
MESSAGE_TITLE_LENGTH = 80


def _display_title(label: str, props: dict[str, Any]) -> str:
    if label == "Author":
        return str(props.get("login") or f"author {props.get('id')}")
    if label == "Channel":
        name = props.get("name")
        return f"#{name}" if name else str(props.get("id"))
    if label == "Message":
        body = " ".join((props.get("body") or "").split())
        if not body:
            return "(no text)"
        if len(body) <= MESSAGE_TITLE_LENGTH:
            return body
        return body[: MESSAGE_TITLE_LENGTH - 1].rstrip() + "\u2026"
    number = props.get("number")
    title = props.get("title") or ""
    return f"#{number} {title}".strip() if number is not None else title


def _node_payload(labels: list[str], props: dict[str, Any]) -> dict[str, Any]:
    label = _primary_label(labels)
    return {
        "key": node_key(labels, props.get("id")),
        "id": props.get("id"),
        "type": label,
        "title": _display_title(label, props),
        "url": props.get("html_url"),
        "state": props.get("state"),
        "repo": props.get("repo"),
        "number": props.get("number"),
    }


def fetch_graph(
    driver: Driver,
    workspace_id: str | uuid.UUID,
    *,
    node_limit: int = DEFAULT_NODE_LIMIT,
    edge_limit: int = DEFAULT_EDGE_LIMIT,
) -> GraphPayload:
    """Every node and edge in one workspace, in a single read transaction.

    Edges referencing a node dropped by ``node_limit`` are discarded, so the
    client never receives a dangling endpoint.
    """
    workspace = normalise_workspace_id(workspace_id)

    def work(tx) -> tuple[list, list]:
        nodes = list(
            tx.run(NODES_QUERY, workspace_id=workspace, limit=node_limit)
        )
        edges = list(
            tx.run(EDGES_QUERY, workspace_id=workspace, limit=edge_limit)
        )
        return nodes, edges

    with driver.session() as session:
        node_records, edge_records = session.execute_read(work)

    nodes = [_node_payload(r["labels"], r["props"]) for r in node_records]
    present = {n["key"] for n in nodes}

    edges = []
    dropped = 0
    for record in edge_records:
        source = node_key(record["source_labels"], record["source_id"])
        target = node_key(record["target_labels"], record["target_id"])
        if source in present and target in present:
            edges.append({"source": source, "target": target, "type": record["type"]})
        else:
            dropped += 1

    truncated = (
        len(node_records) >= node_limit or len(edge_records) >= edge_limit or dropped > 0
    )
    return GraphPayload(
        workspace_id=workspace, nodes=nodes, edges=edges, truncated=truncated
    )


def fetch_source_summaries(
    driver: Driver, workspace_id: str | uuid.UUID
) -> list[SourceSummaryPayload]:
    """Summarise every connected source and its indexed graph items.

    Two reads in one transaction rather than one union query: repositories group
    on ``repo`` and count pull requests and issues, chat connections group on
    ``source_ref`` and count channels and messages. Forcing them into a single
    aggregation would make both halves harder to read than the merge below.
    """
    workspace = normalise_workspace_id(workspace_id)

    def work(tx) -> tuple[list, list]:
        repos = list(tx.run(SOURCES_QUERY, workspace_id=workspace))
        chats = list(tx.run(CHAT_SOURCES_QUERY, workspace_id=workspace))
        return repos, chats

    with driver.session() as session:
        repo_records, chat_records = session.execute_read(work)

    summaries = [
        SourceSummaryPayload(
            repo=str(record["repo"]),
            pull_requests=int(record["pull_requests"]),
            issues=int(record["issues"]),
            total_items=int(record["total_items"]),
        )
        for record in repo_records
    ]
    summaries.extend(
        SourceSummaryPayload(
            repo=str(record["source_ref"]),
            channels=int(record["channels"]),
            messages=int(record["messages"]),
            kind=record["kind"],
            # A channel is an item the connection contributed, same as a message.
            total_items=int(record["channels"]) + int(record["messages"]),
        )
        for record in chat_records
    )
    summaries.sort(key=lambda summary: (summary.repo.lower(), summary.repo))
    return summaries


def _origin(
    labels: list[str],
    props: dict[str, Any],
    relationship: str | None = None,
    direction: str | None = None,
) -> dict[str, Any] | None:
    url = props.get("html_url")
    if not url:
        return None
    label = _primary_label(labels)
    origin: dict[str, Any] = {
        "key": node_key(labels, props.get("id")),
        "type": label,
        "title": _display_title(label, props),
        "url": url,
        "relationship": relationship,
        "direction": direction,
    }
    return origin


def _details_payload(
    labels: list[str], props: dict[str, Any], connected=()
) -> dict[str, Any]:
    label = _primary_label(labels)
    attributes = {key: value for key, value in props.items() if key != "workspace_id"}
    origins = []
    own_origin = _origin(labels, props)
    if own_origin:
        origins.append(own_origin)
    for item in connected:
        if not item:
            continue
        origin = _origin(
            item["labels"], item["props"], item["relationship"], item["direction"]
        )
        if origin:
            origins.append(origin)
    return {
        "key": node_key(labels, props.get("id")),
        "id": props.get("id"),
        "type": label,
        "title": _display_title(label, props),
        "content": props.get("body"),
        "attributes": attributes,
        "origins": origins,
    }


def fetch_node_details(
    driver: Driver,
    workspace_id: str | uuid.UUID,
    node_type: str,
    node_id: int | str,
) -> dict[str, Any] | None:
    """Fetch a workspace node and its directly connected provenance."""
    workspace = normalise_workspace_id(workspace_id)

    def work(tx):
        return tx.run(
            NODE_DETAILS_QUERY,
            workspace_id=workspace,
            node_type=node_type,
            node_id=node_id,
            origin_limit=DEFAULT_ORIGIN_LIMIT,
        ).single()

    with driver.session() as session:
        record = session.execute_read(work)
    if record is None:
        return None
    return _details_payload(record["labels"], record["props"], record["connected"])


def coerce_node_id(raw: str) -> int | str:
    """Recover a node id's type from its text form.

    GitHub ids are integers in the graph and chat ids are provider-prefixed
    strings, but a node key is text either way -- and Neo4j will not match 42
    against "42". Every chat id contains a ``/`` (see
    ``app.sources.chat_graph``), so this attempt fails for all of them and
    succeeds for every GitHub id.
    """
    try:
        return int(raw)
    except ValueError:
        return raw


def _parse_node_key(key: str) -> tuple[str, int | str]:
    node_type, separator, raw_id = key.partition(":")
    if not separator or node_type not in GRAPH_LABELS or not raw_id:
        raise ValueError("Invalid graph node key")
    return node_type, coerce_node_id(raw_id)


def fetch_edge_details(
    driver: Driver,
    workspace_id: str | uuid.UUID,
    source_key: str,
    target_key: str,
    edge_type: str,
) -> dict[str, Any] | None:
    """Fetch one workspace edge and both endpoints."""
    workspace = normalise_workspace_id(workspace_id)
    source_type, source_id = _parse_node_key(source_key)
    target_type, target_id = _parse_node_key(target_key)

    def work(tx):
        return tx.run(
            EDGE_DETAILS_QUERY,
            workspace_id=workspace,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            edge_type=edge_type,
        ).single()

    with driver.session() as session:
        record = session.execute_read(work)
    if record is None:
        return None

    source = _details_payload(record["source_labels"], record["source_props"])
    target = _details_payload(record["target_labels"], record["target_props"])
    relation_props = record["props"]
    content = relation_props.get("evidence") or relation_props.get("content") or (
        f"{source['title']} is connected to {target['title']} by {record['type']}."
    )
    return {
        "key": f"{source_key}|{record['type']}|{target_key}",
        "type": record["type"],
        "title": record["type"].replace("_", " ").title(),
        "content": content,
        "source": source,
        "target": target,
        "attributes": relation_props,
        "origins": source["origins"] + target["origins"],
    }
