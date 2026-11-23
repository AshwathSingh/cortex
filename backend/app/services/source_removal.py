"""Resumable cross-store deletion. Workspace locks serialize graph writers.

Persist target keys BEFORE touching Neo4j: if the graph commit succeeds but
Postgres fails, a retry can still remove the original comments/read markers.
Completed journals keep a revision and removed target identifiers, fencing stale writes.
Flags and their evidence are derived on read, so disappear with their graph items.
"""

import uuid
from contextlib import contextmanager
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from neo4j import Driver
from app.models import (
    DataSource,
    GraphComment,
    GraphCommentView,
    SourceRemoval,
    SyncStatus,
    Workspace,
)
from app.graph.queries import node_key
from app.services.workspaces import lock_active_workspace
from app.uploads.graph import document_id


class SourceChanged(Exception):
    pass


def canonical_ref(kind: str, ref: str) -> str:
    return ref.strip().lower() if kind == "upload" else ref


def journal(
    session: Session, workspace_id: uuid.UUID, kind: str, ref: str
) -> SourceRemoval | None:
    return session.scalar(
        select(SourceRemoval)
        .where(
            SourceRemoval.workspace_id == workspace_id,
            SourceRemoval.kind == kind,
            SourceRemoval.external_ref == canonical_ref(kind, ref),
        )
        .execution_options(populate_existing=True)
    )


def ingestion_fence(
    session: Session, workspace_id: uuid.UUID, kind: str, ref: str
) -> str | None:
    row = journal(session, workspace_id, kind, ref)
    if row and row.pending:
        raise SourceChanged(
            "Source removal is incomplete. Retry removal before ingesting again."
        )
    return row.revision if row else None


def check_ingestion_fence(
    session: Session, workspace_id: uuid.UUID, kind: str, ref: str, revision: str | None
) -> None:
    if ingestion_fence(session, workspace_id, kind, ref) != revision:
        raise SourceChanged(
            "This source was removed during ingestion. Nothing was written."
        )


# Author ownership is relational: source_ref is overwritten when chat authors
# appear in several servers. Preserve authors with ANY link to surviving data.
PLAN = """
MATCH (n {workspace_id: $workspace_id})
WHERE ($kind = 'github' AND (n:Repository OR n:PullRequest OR n:Issue) AND n.repo = $ref)
   OR ($kind = 'upload' AND ((n:Document AND n.id = $document_id)
       OR (n:DocumentSection AND n.document_id = $document_id)))
   OR ($kind IN ['slack', 'discord'] AND n.kind = $kind AND n.source_ref = $ref
       AND ((n:Channel AND ($channel_id IS NULL OR n.id = $channel_id))
         OR (n:Message AND ($channel_id IS NULL OR n.channel_id = $channel_id))))
WITH collect(n) AS owned
OPTIONAL MATCH (a:Author {workspace_id: $workspace_id})--(n)
WHERE n IN owned AND NOT EXISTS { MATCH (a)--(other) WHERE NOT other IN owned }
WITH owned, collect(DISTINCT a) AS authors
WITH owned + authors AS doomed
UNWIND doomed AS n
RETURN elementId(n) AS element_id, labels(n) AS labels, n.id AS id,
       [(n)-[r]-() | {source_labels: labels(startNode(r)), source_id: startNode(r).id,
          target_labels: labels(endNode(r)), target_id: endNode(r).id, type: type(r)}] AS edges,
       [(n)--(a:Author) | {labels: labels(a), id: a.id}] AS authors
"""


def plan_cleanup(
    driver: Driver, workspace_id: uuid.UUID, kind: str, ref: str, channel_id: str | None
) -> dict:
    with driver.session() as graph:
        records = graph.execute_read(
            lambda tx: list(
                tx.run(
                    PLAN,
                    workspace_id=str(workspace_id),
                    kind=kind,
                    ref=ref,
                    document_id=document_id(ref),
                    channel_id=channel_id,
                )
            )
        )
    keys = set()
    for record in records:
        for author in record["authors"]:
            keys.add(node_key(author["labels"], author["id"]))
        if "Repository" not in record["labels"]:
            keys.add(node_key(record["labels"], record["id"]))
        for edge in record["edges"]:
            keys.add(
                f"{node_key(edge['source_labels'], edge['source_id'])}|{edge['type']}|{node_key(edge['target_labels'], edge['target_id'])}"
            )
    return {"keys": sorted(keys)}


def remove_source(
    session: Session,
    driver: Driver,
    workspace_id: uuid.UUID,
    kind: str,
    ref: str,
    channel_id: str | None = None,
) -> None:
    # Exclusive workspace lock conflicts with ingestion's shared write lock.
    # Keep it across graph planning and cleanup; release only after SQL commits.
    def lock():
        session.execute(
            select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
        ).all()
        if not lock_active_workspace(session, workspace_id):
            raise SourceChanged("This workspace is being deleted.")

    lock()
    row = journal(session, workspace_id, kind, ref)
    if row and row.pending and row.channel_id != channel_id:
        raise SourceChanged(
            "Finish the previous source removal before removing another channel."
        )
    if not row or not row.pending:
        targets = plan_cleanup(driver, workspace_id, kind, ref, channel_id)
        targets["keys"] = sorted(
            set(targets["keys"]) | set(row.targets.get("keys", []) if row else [])
        )
        if row is None:
            row = SourceRemoval(
                workspace_id=workspace_id,
                kind=kind,
                external_ref=canonical_ref(kind, ref),
            )
            session.add(row)
        row.revision = str(uuid.uuid4())
        row.pending = True
        row.channel_id = channel_id
        row.targets = targets
        revision = row.revision
        session.commit()
        lock()
        row = journal(session, workspace_id, kind, ref)
        if row.revision != revision or not row.pending:
            return  # another retry completed this cleanup while we reacquired
    targets = row.targets
    with driver.session() as graph:

        def cleanup(tx):
            # Resolve ownership again in the SAME Neo4j transaction as deletion.
            # Never replay saved element ids: Neo4j may reuse deleted ids.
            records = list(
                tx.run(
                    PLAN,
                    workspace_id=str(workspace_id),
                    kind=kind,
                    ref=ref,
                    document_id=document_id(ref),
                    channel_id=channel_id,
                )
            )
            ids = [record["element_id"] for record in records]
            tx.run(
                "MATCH (n {workspace_id: $workspace_id}) WHERE elementId(n) IN $ids DETACH DELETE n",
                workspace_id=str(workspace_id),
                ids=ids,
            ).consume()

        graph.execute_write(cleanup)
        # Keys for surviving shared nodes/edges must retain their discussions.
        existing = graph.execute_read(
            lambda tx: list(
                tx.run(
                    "MATCH (n {workspace_id: $workspace_id}) "
                    "WITH collect(head(labels(n)) + ':' + toString(n.id)) AS node_keys "
                    "OPTIONAL MATCH (a {workspace_id: $workspace_id})-[r]->(b {workspace_id: $workspace_id}) "
                    "WITH node_keys, collect(head(labels(a)) + ':' + toString(a.id) + '|' + type(r) + '|' + head(labels(b)) + ':' + toString(b.id)) AS edge_keys RETURN node_keys + edge_keys AS keys",
                    workspace_id=str(workspace_id),
                )
            )
        )
    surviving = set(existing[0]["keys"]) if existing else set()
    keys = [key for key in targets["keys"] if key not in surviving]
    for model in (GraphComment, GraphCommentView):
        # Bound batches stay below database parameter ceilings for large repos.
        for start in range(0, len(keys), 500):
            session.execute(
                delete(model).where(
                    model.workspace_id == workspace_id,
                    model.target_key.in_(keys[start : start + 500]),
                )
            )
    if channel_id is None:
        predicate = (
            func.lower(func.trim(DataSource.external_ref)) == canonical_ref(kind, ref)
            if kind == "upload"
            else DataSource.external_ref == ref
        )
        session.execute(
            delete(DataSource).where(
                DataSource.workspace_id == workspace_id,
                DataSource.kind == kind,
                predicate,
            )
        )
    else:
        source = session.scalar(
            select(DataSource).where(
                DataSource.workspace_id == workspace_id,
                DataSource.kind == kind,
                DataSource.external_ref == ref,
            )
        )
        if source and source.status == SyncStatus.PENDING:
            source.status = SyncStatus.FAILED
            source.last_error = "Sync stopped because a channel was removed. Choose the remaining channels to ingest again."
            source.last_error_code = "unknown"
    row.pending = False
    row.targets = {"keys": keys}  # Only identifiers; no removed content is retained.
    session.commit()
    # Refresh analysis for surviving artifacts after invalidating an older run.
    from app.agent.events import emit_artifact_ingested

    emit_artifact_ingested(workspace_id)


CHANNELS = """
MATCH (c:Channel {workspace_id: $workspace_id, kind: $kind, source_ref: $ref})
OPTIONAL MATCH (m:Message {workspace_id: $workspace_id, kind: $kind, source_ref: $ref})
WHERE m.channel_id = c.id
RETURN c.id AS id, c.name AS name, count(m) AS messages ORDER BY c.name, c.id
"""


def indexed_channels(
    session: Session, driver: Driver, workspace_id: uuid.UUID, kind: str, ref: str
) -> list[dict]:
    with driver.session() as graph:
        channels = [
            dict(r)
            for r in graph.execute_read(
                lambda tx: list(
                    tx.run(CHANNELS, workspace_id=str(workspace_id), kind=kind, ref=ref)
                )
            )
        ]
    row = journal(session, workspace_id, kind, ref)
    if (
        row
        and row.pending
        and row.channel_id
        and not any(c["id"] == row.channel_id for c in channels)
    ):
        channels.append(
            {"id": row.channel_id, "name": "Removal incomplete — retry", "messages": 0}
        )
    return channels


def guard_target(
    session: Session,
    workspace_id: uuid.UUID,
    target_key: str,
    driver: Driver | None = None,
) -> None:
    """Serialize mutations with cleanup and reject stale inspector submissions.

    Only removed targets need a graph lookup; ordinary comment posting keeps
    its existing availability when Neo4j is offline.
    """
    if not lock_active_workspace(session, workspace_id):
        raise SourceChanged("This workspace is being deleted.")
    rows = session.scalars(
        select(SourceRemoval).where(SourceRemoval.workspace_id == workspace_id)
    ).all()
    matching = [row for row in rows if target_key in row.targets.get("keys", [])]
    if not matching:
        return
    if any(row.pending for row in matching):
        raise SourceChanged(
            "This content is being removed. Refresh the page before continuing."
        )
    if driver is None:
        from app.db.neo4j_driver import get_driver

        driver = get_driver()
    from app.graph.queries import fetch_node_details, fetch_edge_details, coerce_node_id

    if "|" in target_key:
        source, edge_type, target = target_key.split("|")
        exists = fetch_edge_details(driver, workspace_id, source, target, edge_type)
    else:
        label, raw_id = target_key.split(":", 1)
        exists = fetch_node_details(driver, workspace_id, label, coerce_node_id(raw_id))
    if not exists:
        raise SourceChanged(
            "This content has been removed. Refresh the page before continuing."
        )


class SourceRemovalFence:
    """A run snapshots source generations, then locks only during graph writes.

    Remote model calls hold no database locks. Any removal invalidates this run
    even if identical node ids are explicitly ingested again before it returns.
    """

    def __init__(self, workspace_id: str, session_factory=None):
        if session_factory is None:
            from app.db.postgres import get_session_factory

            session_factory = get_session_factory()
        self.workspace_id = uuid.UUID(str(workspace_id))
        self.session_factory = session_factory
        with session_factory() as session:
            self.revisions = self._snapshot(session)

    def _snapshot(self, session):
        if not lock_active_workspace(session, self.workspace_id):
            raise SourceChanged("This workspace was removed during analysis.")
        rows = session.scalars(
            select(SourceRemoval).where(SourceRemoval.workspace_id == self.workspace_id)
        ).all()
        if any(row.pending for row in rows):
            raise SourceChanged(
                "Source removal is in progress; analysis was cancelled."
            )
        return sorted((row.kind, row.external_ref, row.revision) for row in rows)

    @contextmanager
    def write(self):
        with self.session_factory() as session:
            if self._snapshot(session) != self.revisions:
                raise SourceChanged(
                    "Sources changed during analysis; its stale result was discarded."
                )
            yield
