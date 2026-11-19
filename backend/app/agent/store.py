"""T-23.3: the agent's workspace-scoped Neo4j reads. Writes live in
``app.graph.mutations``. Every query filters on ``workspace_id``.
"""

from typing import Any

from neo4j import Driver

from app.agent.candidates import Artifact
from app.agent.relationships import AGENT_EDGE_TYPE
from app.github.mapper import normalise_workspace_id
from app.graph.mutations import ARTIFACT_LABELS, _match, _typed_id, parse_key
from app.graph.queries import node_key

#: Per round trip, not a cap on the workspace's total -- ``fetch_artifacts``
#: pages through all of it, so a workspace past this size is still analysed
#: in full rather than silently dropping everything after the first page.
ARTIFACT_PAGE_SIZE = 5_000
BODY_LIMIT = 2_000  # characters sent to Jev per artifact: the main token-cost lever

_ARTIFACTS = f"""
MATCH (n)
WHERE ({" OR ".join(f"n:{label}" for label in ARTIFACT_LABELS)}) AND n.workspace_id = $ws
OPTIONAL MATCH (a:Author {{workspace_id: $ws}})-[:AUTHORED]->(n)
RETURN labels(n) AS labels, properties(n) AS props, head(collect(a.login)) AS author
ORDER BY props.id
SKIP $skip
LIMIT $limit
"""

def _blocked_query(a_label: str, b_label: str) -> str:
    return f"""
MATCH {_match(a_label, "a")}, {_match(b_label, "b")}
WHERE EXISTS {{ MATCH (a)-[m:MANUAL_RELATIONSHIP]-(b) WHERE m.workspace_id = $ws }}
   OR EXISTS {{ MATCH (a)-[g:{AGENT_EDGE_TYPE}]-(b) WHERE g.workspace_id = $ws AND g.status = 'rejected' }}
RETURN 1 AS blocked
"""

def _existing_for_pair_query(a_label: str, b_label: str) -> str:
    # Undirected and type-agnostic: re-analysis that predicts a different type
    # (or a different direction) for a pair must find the pair's one existing
    # edge by its endpoints, not by a dedup_key that embeds the *old* type --
    # otherwise it would never match and a duplicate edge would be created
    # alongside the stale one.
    return f"""
MATCH {_match(a_label, "a")}, {_match(b_label, "b")}
MATCH (a)-[r:{AGENT_EDGE_TYPE}]-(b)
WHERE r.workspace_id = $ws
RETURN r.id AS id, r.status AS status, r.relationship_type AS relationship_type
LIMIT 1
"""

_SUGGESTIONS = f"""
MATCH (s)-[r:{AGENT_EDGE_TYPE} {{workspace_id: $ws, status: 'pending_review'}}]->(t)
WHERE s.workspace_id = $ws AND t.workspace_id = $ws
RETURN r.id AS id, r.relationship_type AS relationship_type, r.confidence AS confidence,
       r.evidence AS evidence, r.created_at AS created_at,
       labels(s) AS s_labels, properties(s) AS s_props,
       labels(t) AS t_labels, properties(t) AS t_props
ORDER BY r.confidence DESC, r.id
LIMIT $limit
"""

_STATUS_COUNTS = f"""
MATCH (n)
WHERE ({" OR ".join(f"n:{label}" for label in ARTIFACT_LABELS)}) AND n.workspace_id = $ws
RETURN coalesce(n.analysis_status, 'unanalysed') AS status, count(n) AS count
"""

_PENDING_COUNT = f"""
MATCH ()-[r:{AGENT_EDGE_TYPE} {{workspace_id: $ws, status: 'pending_review'}}]->()
RETURN count(r) AS count
"""


def _title(props: dict[str, Any]) -> str:
    number = props.get("number")
    title = props.get("title") or props.get("heading") or props.get("filename") or str(props.get("id"))
    return f"#{number} {title}" if number is not None and props.get("title") else str(title)


def to_artifact(labels: list[str], props: dict[str, Any], author: str | None,
                workspace_id: str) -> Artifact:
    label = next(label for label in labels if label in ARTIFACT_LABELS)
    return Artifact(
        key=node_key(labels, props.get("id")), label=label, id=props.get("id"),
        workspace_id=workspace_id, title=_title(props),
        body=(props.get("body") or "")[:BODY_LIMIT], url=props.get("html_url"),
        repo=props.get("repo"), number=props.get("number"), author=author,
        created_at=props.get("created_at"), analysis_hash=props.get("analysis_hash"),
    )


class Neo4jStore:
    def __init__(self, driver: Driver):
        self.driver = driver

    def fetch_artifacts(self, workspace_id: str) -> list[Artifact]:
        ws = normalise_workspace_id(workspace_id)
        rows: list[Any] = []
        skip = 0
        with self.driver.session() as session:
            while True:
                page = list(session.execute_read(lambda tx: list(
                    tx.run(_ARTIFACTS, ws=ws, skip=skip, limit=ARTIFACT_PAGE_SIZE))))
                rows.extend(page)
                if len(page) < ARTIFACT_PAGE_SIZE:
                    break
                skip += ARTIFACT_PAGE_SIZE
        return [to_artifact(r["labels"], r["props"], r["author"], ws) for r in rows]

    def pair_blocked(self, workspace_id: str, a_key: str, b_key: str) -> bool:
        """A manual edge exists, or a user rejected/removed an agent edge here."""
        ws = normalise_workspace_id(workspace_id)
        (a_label, a_raw), (b_label, b_raw) = parse_key(a_key), parse_key(b_key)
        query = _blocked_query(a_label, b_label)
        with self.driver.session() as session:
            record = session.execute_read(lambda tx: tx.run(
                query, ws=ws, a_id=_typed_id(a_raw), b_id=_typed_id(b_raw)).single())
        return record is not None

    def existing_edge_for_pair(self, workspace_id: str, a_key: str, b_key: str) -> tuple[str, str, str] | None:
        """Any agent edge already linking this pair, in either direction and
        whatever its type -- see ``_existing_for_pair_query``."""
        ws = normalise_workspace_id(workspace_id)
        (a_label, a_raw), (b_label, b_raw) = parse_key(a_key), parse_key(b_key)
        query = _existing_for_pair_query(a_label, b_label)
        with self.driver.session() as session:
            record = session.execute_read(lambda tx: tx.run(
                query, ws=ws, a_id=_typed_id(a_raw), b_id=_typed_id(b_raw)).single())
        return (record["id"], record["status"], record["relationship_type"]) if record else None

    def list_suggestions(self, workspace_id: str, limit: int = 200) -> list[dict[str, Any]]:
        ws = normalise_workspace_id(workspace_id)
        with self.driver.session() as session:
            rows = list(session.execute_read(
                lambda tx: list(tx.run(_SUGGESTIONS, ws=ws, limit=limit))))
        return [
            {
                "id": r["id"], "relationship_type": r["relationship_type"],
                "confidence": r["confidence"], "evidence": r["evidence"],
                "created_at": r["created_at"],
                "source": {"key": node_key(r["s_labels"], r["s_props"].get("id")),
                           "type": r["s_labels"][0], "title": _title(r["s_props"]),
                           "url": r["s_props"].get("html_url")},
                "target": {"key": node_key(r["t_labels"], r["t_props"].get("id")),
                           "type": r["t_labels"][0], "title": _title(r["t_props"]),
                           "url": r["t_props"].get("html_url")},
            }
            for r in rows
        ]

    def analysis_summary(self, workspace_id: str) -> dict[str, int]:
        ws = normalise_workspace_id(workspace_id)
        with self.driver.session() as session:
            counts = session.execute_read(lambda tx: {
                r["status"]: r["count"] for r in tx.run(_STATUS_COUNTS, ws=ws)})
            pending = session.execute_read(
                lambda tx: tx.run(_PENDING_COUNT, ws=ws).single()["count"])
        return {**counts, "pending_review": pending}
