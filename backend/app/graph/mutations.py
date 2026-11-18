"""T-23.4: the shared graph-mutation layer (agent edges, review actions).

Every write the Connection Agent makes goes through here, and every write calls
``record_mutation``. Kuanyu's audit log / timeline (US-22) plugs in with
``add_mutation_listener``; until it lands there are no listeners and nothing
else changes. ``actor`` is ``"system:connection_agent"`` or ``"user:<id>"``.

Every statement is scoped by ``workspace_id`` on both endpoints.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neo4j import Driver

from app.agent.relationships import AGENT_EDGE_TYPE, SOURCE_AGENT
from app.github.mapper import normalise_workspace_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MutationEvent:
    workspace_id: str
    actor: str
    action: str  # edge.created | edge.updated | edge.promoted | edge.approved | edge.rejected
    edge_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


_listeners: list[Callable[[MutationEvent], None]] = []


def add_mutation_listener(listener: Callable[[MutationEvent], None]) -> None:
    _listeners.append(listener)


def record_mutation(event: MutationEvent) -> None:
    # An audit hook must never be able to fail the write it describes.
    for listener in list(_listeners):
        try:
            listener(event)
        except Exception:
            logger.exception("mutation listener failed")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_key(key: str) -> tuple[str, str]:
    label, _, raw = key.partition(":")
    return label, raw


# Labels are interpolated into Cypher, so they must come from this closed set.
ARTIFACT_LABELS: tuple[str, ...] = ("PullRequest", "Issue", "DocumentSection")


def _match(label: str, var: str) -> str:
    if label not in ARTIFACT_LABELS:
        raise ValueError(f"not an analysable label: {label!r}")
    return f"({var}:{label} {{id: ${var}_id, workspace_id: $ws}})"


def _typed_id(raw: str) -> int | str:
    # GitHub ids are ints in the graph; upload/chat ids are prefixed strings.
    try:
        return int(raw)
    except ValueError:
        return raw


def create_agent_edge(
    driver: Driver, workspace_id: str, *, source_key: str, target_key: str,
    relationship_type: str, dedup: str, status: str, confidence: float,
    evidence: str, model_version: str, explicit_refs: list[str],
) -> str | None:
    """Create one agent edge. Returns its id, or None if an endpoint is missing."""
    ws = normalise_workspace_id(workspace_id)
    s_label, s_raw = parse_key(source_key)
    t_label, t_raw = parse_key(target_key)
    edge_id, ts = str(uuid.uuid4()), now_iso()
    query = f"""
MATCH {_match(s_label, "s")}
MATCH {_match(t_label, "t")}
CREATE (s)-[r:{AGENT_EDGE_TYPE} {{
  id: $edge_id, workspace_id: $ws, relationship_type: $rtype, origin: 'agent',
  source_agent: $agent, model_version: $model, agent_version: $agent_version,
  status: $status, confidence: $confidence, evidence: $evidence,
  explicit_refs: $refs, dedup_key: $dedup, created_at: $ts, updated_at: $ts
}}]->(t)
RETURN r.id AS id
"""
    with driver.session() as session:
        record = session.execute_write(lambda tx: tx.run(
            query, s_id=_typed_id(s_raw), t_id=_typed_id(t_raw), ws=ws, edge_id=edge_id,
            rtype=relationship_type, agent=SOURCE_AGENT, model=model_version,
            agent_version="1", status=status, confidence=confidence, evidence=evidence,
            refs=explicit_refs, dedup=dedup, ts=ts,
        ).single())
    if record is None:
        return None
    record_mutation(MutationEvent(ws, f"system:{SOURCE_AGENT}", "edge.created", edge_id,
                                  {"status": status, "relationship_type": relationship_type}))
    return edge_id


def update_agent_edge(
    driver: Driver, workspace_id: str, *, edge_id: str, confidence: float,
    evidence: str, model_version: str, explicit_refs: list[str], promote: bool,
) -> None:
    """Refresh an existing agent edge; ``promote`` flips pending_review -> active.

    Never touches ``rejected`` edges or reviewer fields (guarded in the WHERE).
    """
    ws = normalise_workspace_id(workspace_id)
    query = f"""
MATCH ()-[r:{AGENT_EDGE_TYPE} {{id: $edge_id, workspace_id: $ws}}]->()
WHERE r.status IN ['active', 'pending_review']
SET r.confidence = $confidence, r.evidence = $evidence, r.model_version = $model,
    r.explicit_refs = $refs, r.updated_at = $ts,
    r.status = CASE WHEN $promote AND r.status = 'pending_review' THEN 'active' ELSE r.status END
RETURN r.id AS id
"""
    with driver.session() as session:
        record = session.execute_write(lambda tx: tx.run(
            query, edge_id=edge_id, ws=ws, confidence=confidence, evidence=evidence,
            model=model_version, refs=explicit_refs, ts=now_iso(), promote=promote,
        ).single())
    if record is not None:
        record_mutation(MutationEvent(
            ws, f"system:{SOURCE_AGENT}", "edge.promoted" if promote else "edge.updated", edge_id))


def review_agent_edge(
    driver: Driver, workspace_id: str, *, edge_id: str, approve: bool, user_id: str,
) -> bool:
    """Approve or reject a pending_review edge. False if it is not pending."""
    ws = normalise_workspace_id(workspace_id)
    query = f"""
MATCH ()-[r:{AGENT_EDGE_TYPE} {{id: $edge_id, workspace_id: $ws, status: 'pending_review'}}]->()
SET r.status = $status, r.reviewed_by = $user, r.reviewed_at = $ts, r.updated_at = $ts
RETURN r.id AS id
"""
    with driver.session() as session:
        record = session.execute_write(lambda tx: tx.run(
            query, edge_id=edge_id, ws=ws, user=user_id, ts=now_iso(),
            status="active" if approve else "rejected",
        ).single())
    if record is None:
        return False
    record_mutation(MutationEvent(
        ws, f"user:{user_id}", "edge.approved" if approve else "edge.rejected", edge_id))
    return True


def reject_agent_edge_by_endpoints(
    driver: Driver, workspace_id: str, *, source_label: str, source_id: Any,
    target_label: str, target_id: Any, edge_type: str, user_id: str,
) -> bool:
    """The existing "remove relationship" action, for an agent edge.

    Soft-removes: the edge becomes ``rejected`` (excluded from every read) so it
    doubles as the tombstone that stops the agent re-suggesting the pair.
    """
    ws = normalise_workspace_id(workspace_id)
    query = f"""
MATCH {_match(source_label, "s")}-[r:{AGENT_EDGE_TYPE}]->{_match(target_label, "t")}
WHERE type(r) = $edge_type AND r.workspace_id = $ws AND r.status <> 'rejected'
SET r.status = 'rejected', r.reviewed_by = $user, r.reviewed_at = $ts, r.updated_at = $ts
RETURN r.id AS id
"""
    with driver.session() as session:
        record = session.execute_write(lambda tx: tx.run(
            query, s_id=source_id, t_id=target_id, ws=ws, edge_type=edge_type,
            user=user_id, ts=now_iso(),
        ).single())
    if record is None:
        return False
    record_mutation(MutationEvent(ws, f"user:{user_id}", "edge.removed", record["id"]))
    return True


def set_analysis_status(
    driver: Driver, workspace_id: str, artifact_key: str, status: str, *,
    content_hash: str | None = None, error: str | None = None,
) -> None:
    """Per-artifact analysis state: pending | running | done | failed.

    Only ``done`` records the content hash, so a failed or interrupted artifact
    stays eligible for the next run. ``error`` is a short, secret-free summary.
    """
    ws = normalise_workspace_id(workspace_id)
    label, raw = parse_key(artifact_key)
    query = f"""
MATCH {_match(label, "n")}
SET n.analysis_status = $status, n.analysis_error = $error,
    n.analysis_hash = CASE WHEN $status = 'done' THEN $hash ELSE n.analysis_hash END,
    n.analyzed_at = CASE WHEN $status = 'done' THEN $ts ELSE n.analyzed_at END
"""
    with driver.session() as session:
        session.execute_write(lambda tx: tx.run(
            query, n_id=_typed_id(raw), ws=ws, status=status, error=error,
            hash=content_hash, ts=now_iso(),
        ).consume())
