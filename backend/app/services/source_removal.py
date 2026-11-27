"""Resumable cross-store deletion. Workspace locks serialize graph writers.

Persist target keys BEFORE touching Neo4j: if the graph commit succeeds but
Postgres fails, a retry can still remove the original comments/read markers.
Completed journals keep a revision and removed target identifiers, fencing stale writes.
Flags and their evidence are derived on read, so disappear with their graph items.
"""

import uuid
from contextlib import contextmanager
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from neo4j import Driver
from app.models import (
    DataSource,
    GraphComment,
    GraphCommentView,
    SourceRemoval,
    SourceRemovalTarget,
    WORKSPACE_ACTIVE,
    SyncStatus,
    Workspace,
)
from app.graph import mutations
from app.graph.queries import node_key, parse_graph_target_key, coerce_node_id
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


def plan_cleanup(
    driver: Driver, workspace_id: uuid.UUID, kind: str, ref: str, channel_id: str | None
) -> dict:
    records = mutations.fetch_source_removal_plan(
        driver, workspace_id, kind, ref, channel_id
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


def _surviving_keys(driver, workspace_id, keys):
    # Return raw labels/ids and use the SAME node_key helper as the canvas and
    # cleanup plan. Extra labels must never erase a surviving node's discussion.
    ids = list(
        dict.fromkeys(
            coerce_node_id(endpoint.partition(":")[2])
            for key in keys
            for endpoint in key.split("|")[::2]
        )
    )
    if not ids:
        return set()

    def read(tx):
        nodes = list(
            tx.run(
                "MATCH (n {workspace_id: $ws}) WHERE n.id IN $ids RETURN labels(n) AS labels, n.id AS id",
                ws=str(workspace_id),
                ids=ids,
            )
        )
        edges = list(
            tx.run(
                "MATCH (a {workspace_id: $ws})-[r]->(b {workspace_id: $ws}) WHERE a.id IN $ids AND b.id IN $ids RETURN labels(a) AS source_labels, a.id AS source_id, labels(b) AS target_labels, b.id AS target_id, type(r) AS type",
                ws=str(workspace_id),
                ids=ids,
            )
        )
        return nodes, edges

    with driver.session() as graph:
        nodes, edges = graph.execute_read(read)
    surviving = {node_key(row["labels"], row["id"]) for row in nodes}
    surviving.update(
        f"{node_key(row['source_labels'], row['source_id'])}|{row['type']}|{node_key(row['target_labels'], row['target_id'])}"
        for row in edges
    )
    return surviving


def remove_source(
    session: Session,
    driver: Driver,
    workspace_id: uuid.UUID,
    kind: str,
    ref: str,
    channel_id: str | None = None,
    *,
    actor: str = "system:source_removal",
) -> None:
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
        previous = (
            set(
                session.scalars(
                    select(SourceRemovalTarget.target_key).where(
                        SourceRemovalTarget.workspace_id == workspace_id,
                        SourceRemovalTarget.source_removal_id == row.id,
                    )
                ).all()
            )
            if row
            else set()
        )
        targets["keys"] = sorted(set(targets["keys"]) | previous)
        if row is None:
            row = SourceRemoval(
                workspace_id=workspace_id,
                kind=kind,
                external_ref=canonical_ref(kind, ref),
            )
            session.add(row)
        row.revision = str(uuid.uuid4())
        row.pending, row.channel_id, row.targets = True, channel_id, targets
        session.flush()
        for key in set(targets["keys"]) - previous:
            session.add(
                SourceRemovalTarget(
                    workspace_id=workspace_id, source_removal_id=row.id, target_key=key
                )
            )
        session.execute(
            update(Workspace)
            .where(Workspace.id == workspace_id)
            .values(
                source_removal_revision=Workspace.source_removal_revision + 1,
                source_removals_pending=Workspace.source_removals_pending + 1,
            )
        )
        revision = row.revision
        session.commit()
        lock()
        row = journal(session, workspace_id, kind, ref)
        if row.revision != revision or not row.pending:
            return
    targets = row.targets
    operation_id = row.revision
    nodes_removed = mutations.delete_source_graph(
        driver,
        workspace_id,
        kind,
        ref,
        channel_id,
        actor=actor,
        operation_id=operation_id,
    )
    surviving = _surviving_keys(driver, workspace_id, targets["keys"])
    keys = [key for key in targets["keys"] if key not in surviving]
    counts = {
        "nodes_removed": nodes_removed,
        "comments_removed": 0,
        "read_markers_removed": 0,
        "sources_removed": 0,
    }
    for model, label in (
        (GraphComment, "comments_removed"),
        (GraphCommentView, "read_markers_removed"),
    ):
        for start in range(0, len(keys), 500):
            result = session.execute(
                delete(model).where(
                    model.workspace_id == workspace_id,
                    model.target_key.in_(keys[start : start + 500]),
                )
            )
            counts[label] += result.rowcount
    # Remove temporary guards for shared/restored targets, retaining only the
    # identifiers that are genuinely gone. Completed journals hold no key arrays.
    kept = list(surviving.intersection(targets["keys"]))
    for start in range(0, len(kept), 500):
        session.execute(
            delete(SourceRemovalTarget).where(
                SourceRemovalTarget.source_removal_id == row.id,
                SourceRemovalTarget.workspace_id == workspace_id,
                SourceRemovalTarget.target_key.in_(kept[start : start + 500]),
            )
        )
    if channel_id is None:
        predicate = (
            func.lower(func.trim(DataSource.external_ref)) == canonical_ref(kind, ref)
            if kind == "upload"
            else DataSource.external_ref == ref
        )
        result = session.execute(
            delete(DataSource).where(
                DataSource.workspace_id == workspace_id,
                DataSource.kind == kind,
                predicate,
            )
        )
        counts["sources_removed"] = result.rowcount
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
    row.pending, row.targets = False, {}
    session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(source_removals_pending=Workspace.source_removals_pending - 1)
    )
    session.commit()
    if any(counts.values()):
        mutations.record_source_removed(
            workspace_id,
            actor=actor,
            operation_id=operation_id,
            kind=kind,
            ref=ref,
            channel_id=channel_id,
            counts=counts,
        )
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
    if row and row.pending and row.channel_id:
        channel = next(
            (item for item in channels if item["id"] == row.channel_id), None
        )
        if channel is None:
            channel = {
                "id": row.channel_id,
                "name": row.channel_id.split("/", 1)[-1],
                "messages": 0,
            }
            channels.append(channel)
        channel["removal_pending"] = True
    return channels


def guard_target(
    session: Session,
    workspace_id: uuid.UUID,
    target_key: str,
    driver: Driver | None = None,
) -> None:
    source, edge_type, target = parse_graph_target_key(target_key)
    key = target_key.strip()
    if not lock_active_workspace(session, workspace_id):
        raise SourceChanged("This workspace is being deleted.")
    # Indexed lookup of ONE key; never deserialize historical cleanup plans.
    matches = session.execute(
        select(SourceRemoval.pending, SourceRemovalTarget.source_removal_id)
        .join(SourceRemoval, SourceRemoval.id == SourceRemovalTarget.source_removal_id)
        .where(
            SourceRemovalTarget.workspace_id == workspace_id,
            SourceRemoval.workspace_id == workspace_id,
            SourceRemovalTarget.target_key == key,
        )
    ).all()
    if not matches:
        return
    if any(row.pending for row in matches):
        raise SourceChanged(
            "This content is being removed. Refresh the page before continuing."
        )
    if driver is None:
        from app.db.neo4j_driver import get_driver

        driver = get_driver()
    from app.graph.queries import fetch_node_details, fetch_edge_details

    if edge_type is not None:
        exists = fetch_edge_details(driver, workspace_id, source, target, edge_type)
    else:
        label, raw_id = source.split(":", 1)
        exists = fetch_node_details(driver, workspace_id, label, coerce_node_id(raw_id))
    if not exists:
        raise SourceChanged(
            "This content has been removed. Refresh the page before continuing."
        )
    # Explicitly re-added targets no longer need historical tombstones. The
    # shared workspace lock keeps this pruning atomic with the caller's write.
    session.execute(
        delete(SourceRemovalTarget).where(
            SourceRemovalTarget.workspace_id == workspace_id,
            SourceRemovalTarget.target_key == key,
        )
    )


class SourceRemovalFence:
    """Reuse one session and compare one locked workspace row before writes.

    The initial revision is fetched once; it MUST be revalidated under a shared
    lock at each graph write. No transaction/connection is held during Jev calls.
    """

    def __init__(self, workspace_id: str, session_factory=None):
        if session_factory is None:
            from app.db.postgres import get_session_factory

            session_factory = get_session_factory()
        self.workspace_id = uuid.UUID(str(workspace_id))
        self.session = session_factory()
        try:
            self.revision = self._snapshot()
            self.session.rollback()
        except Exception:
            self.session.close()
            raise

    def _snapshot(self):
        row = self.session.execute(
            select(
                Workspace.status,
                Workspace.source_removal_revision,
                Workspace.source_removals_pending,
            )
            .where(Workspace.id == self.workspace_id)
            .with_for_update(read=True)
        ).one_or_none()
        if row is None or row.status != WORKSPACE_ACTIVE:
            raise SourceChanged("This workspace was removed during analysis.")
        if row.source_removals_pending:
            raise SourceChanged(
                "Source removal is in progress; analysis was cancelled."
            )
        return row.source_removal_revision

    @contextmanager
    def write(self):
        with self.session.begin():
            if self._snapshot() != self.revision:
                raise SourceChanged(
                    "Sources changed during analysis; its stale result was discarded."
                )
            yield

    def __call__(self):
        return self.write()

    def close(self):
        self.session.close()
