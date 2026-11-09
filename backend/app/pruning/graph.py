"""T-28.1: loading what the pruning rules need out of Neo4j.

One read per run: every pull request and issue in the workspace, with its author
if it has one. Deliberately separate from ``app.pruning.detect`` so the rules
stay pure functions over plain data -- that is what makes the thresholds and the
edge cases testable without a database.

Scoping is ``n.workspace_id = $workspace_id`` and nothing else, the same single
predicate the Graph Explorer uses (see ``app.graph.queries``), with the same
normaliser so read and write cannot disagree about the canonical form of a UUID.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from neo4j import Driver

from app.github.mapper import normalise_workspace_id
from app.graph.queries import node_key
from app.pruning.detect import GraphItem

#: Ceiling, so one enormous workspace cannot stall the request. Matches the
#: Graph Explorer's node limit: the review queue should consider exactly what
#: the canvas can show.
DEFAULT_ITEM_LIMIT = 2_000

ITEMS_QUERY = """
MATCH (n)
WHERE (n:PullRequest OR n:Issue) AND n.workspace_id = $workspace_id
OPTIONAL MATCH (a:Author)-[:AUTHORED]->(n)
WHERE a.workspace_id = $workspace_id
WITH n, a
ORDER BY head(labels(n)), n.id
LIMIT $limit
RETURN labels(n) AS labels, properties(n) AS props, a.login AS author_login
"""


def _parse_time(value: Any) -> datetime | None:
    """ISO-8601 from the mapper, or a Neo4j temporal, or nothing.

    The mapper writes ISO strings (``model_dump(mode="json")``), but a node
    written by hand or by a future importer could carry a real temporal type, so
    both are accepted. Anything unparseable becomes None and the rules treat it
    as unknown rather than guessing.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = value.to_native()  # neo4j.time.DateTime
            except AttributeError:
                return None
    # Naive timestamps are treated as the UTC they are: GitHub serves UTC and
    # comparing an aware "now" against a naive value would raise.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _item(labels: list[str], props: dict[str, Any], author_login: Any) -> GraphItem:
    label = "PullRequest" if "PullRequest" in labels else "Issue"
    body = props.get("body")
    return GraphItem(
        key=node_key(labels, props.get("id")),
        type=label,
        title=str(props.get("title") or ""),
        repo=props.get("repo"),
        number=props.get("number"),
        url=props.get("html_url"),
        state=props.get("state"),
        body="" if body is None else str(body),
        created_at=_parse_time(props.get("created_at")),
        updated_at=_parse_time(props.get("updated_at")),
        closed_at=_parse_time(props.get("closed_at")),
        merged_at=_parse_time(props.get("merged_at")),
        author_login=str(author_login) if author_login else None,
    )


def fetch_items(
    driver: Driver,
    workspace_id: str | uuid.UUID,
    *,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> tuple[list[GraphItem], bool]:
    """Every item the rules should consider, and whether the ceiling was hit."""
    workspace = normalise_workspace_id(workspace_id)

    def work(tx):
        return list(tx.run(ITEMS_QUERY, workspace_id=workspace, limit=limit))

    with driver.session() as session:
        records = session.execute_read(work)

    items = [
        _item(record["labels"], record["props"], record["author_login"])
        for record in records
    ]
    return items, len(items) >= limit
