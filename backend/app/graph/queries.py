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
GRAPH_LABELS: tuple[str, ...] = ("Author", "PullRequest", "Issue")

# Ceilings so one enormous workspace cannot stall the browser or the API. The
# response reports whether either was hit.
DEFAULT_NODE_LIMIT = 2_000
DEFAULT_EDGE_LIMIT = 6_000


def _label_predicate(variable: str) -> str:
    return " OR ".join(f"{variable}:{label}" for label in GRAPH_LABELS)


NODES_QUERY = f"""
MATCH (n)
WHERE ({_label_predicate("n")}) AND n.workspace_id = $workspace_id
RETURN labels(n) AS labels, properties(n) AS props
LIMIT $limit
"""

EDGES_QUERY = f"""
MATCH (a)-[r]->(b)
WHERE ({_label_predicate("a")}) AND ({_label_predicate("b")})
  AND a.workspace_id = $workspace_id AND b.workspace_id = $workspace_id
RETURN labels(a) AS source_labels, a.id AS source_id,
       labels(b) AS target_labels, b.id AS target_id,
       type(r) AS type
LIMIT $limit
"""


@dataclass
class GraphPayload:
    """What the endpoint serialises. Keys are stable; the frontend builds on them."""

    workspace_id: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


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


def _display_title(label: str, props: dict[str, Any]) -> str:
    if label == "Author":
        return str(props.get("login") or f"author {props.get('id')}")
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
