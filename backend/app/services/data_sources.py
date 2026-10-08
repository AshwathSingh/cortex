"""T-10.1: reading and writing a workspace's data-source sync state.

Three writes, in the order ``POST /api/ingest/github`` performs them:

    record_sync_attempt   PENDING + last_attempted_at, *before* the fetch
    record_sync_success   SUCCESS, last_synced_at/by, last_error cleared
    record_sync_failure   FAILED  + last_error, last_synced_at left alone

Ingestion is synchronous and a large repository takes minutes, so the attempt is
recorded (and committed) before the fetch starts: that is what lets the Sources
page show "Syncing…" while it runs, and what leaves a trace if the request dies
half way. ``last_synced_at`` is never touched by a failure -- see the column
comments in ``app.models.data_source``.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.graph.queries import SourceSummaryPayload
from app.models import GITHUB_KIND, DataSource, SyncStatus, User

#: ``last_error`` is shown in the UI next to the source, not used as a log.
MAX_ERROR_LENGTH = 500

#: How long a PENDING row holds the source against a second ingestion.
#:
#: Ingestion is one synchronous request with nowhere to send a heartbeat from,
#: so this is a lease with a fixed TTL rather than a liveness check: it stops
#: two ingestions of the same source overlapping, and expires so that a request
#: killed mid-flight cannot hold the source forever. The window is deliberately
#: wider than any plausible run -- the GitHub client waits up to 15 minutes for
#: a single rate-limit reset and may hit several.
#:
#: A real heartbeat needs the background job queue that US-7's README defers;
#: until then an ingestion that outlives the lease can still be overlapped, and
#: the two runs race to write the final status. The graph itself is safe either
#: way: every write is a MERGE on the composite key.
SYNC_LEASE = timedelta(minutes=30)


class SyncInProgress(Exception):
    """Another ingestion of this source is already running."""

    def __init__(self, external_ref: str, started_at: datetime):
        super().__init__(external_ref)
        self.external_ref = external_ref
        self.started_at = started_at


@dataclass(frozen=True)
class SyncedSource:
    """A source row plus the display name of whoever last synced it."""

    source: DataSource
    last_synced_by_name: str | None


@dataclass(frozen=True)
class SourceInventoryItem:
    """One row of the Sources page: sync state from Postgres, counts from Neo4j."""

    repo: str
    kind: str
    status: SyncStatus
    pull_requests: int
    issues: int
    total_items: int
    last_attempted_at: datetime | None
    last_synced_at: datetime | None
    last_error: str | None
    last_synced_by: uuid.UUID | None
    last_synced_by_name: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _find(
    session: Session, workspace_id: uuid.UUID, kind: str, external_ref: str
) -> DataSource | None:
    return session.scalar(
        select(DataSource).where(
            DataSource.workspace_id == workspace_id,
            DataSource.kind == kind,
            DataSource.external_ref == external_ref,
        )
    )


def _upsert(
    session: Session, workspace_id: uuid.UUID, kind: str, external_ref: str
) -> tuple[DataSource, bool]:
    """The row for this source and whether this call created it.

    An existing row is returned untouched: only the three ``record_*``
    functions below decide what a write means. The flag matters for the lease --
    a row this call just created cannot be held by anybody else.
    """
    source = _find(session, workspace_id, kind, external_ref)
    if source is not None:
        return source, False

    source = DataSource(
        workspace_id=workspace_id,
        kind=kind,
        external_ref=external_ref,
        status=SyncStatus.PENDING,
        last_attempted_at=_now(),
    )
    try:
        # A savepoint, not the request's transaction: two people connecting the
        # same repo at once would otherwise lose the loser's whole request to a
        # unique-constraint violation.
        with session.begin_nested():
            session.add(source)
    except IntegrityError:
        existing = _find(session, workspace_id, kind, external_ref)
        if existing is None:  # pragma: no cover - the conflicting row must exist
            raise
        return existing, False
    return source, True


def _holds_lease(source: DataSource, now: datetime) -> bool:
    if source.status is not SyncStatus.PENDING:
        return False
    started = source.last_attempted_at
    if started is None:
        return False
    # SQLite drops the timezone; treat a naive timestamp as the UTC it was.
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return now - started < SYNC_LEASE


def record_sync_attempt(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    external_ref: str,
    kind: str = GITHUB_KIND,
) -> DataSource:
    """Take the lease on this source and mark it PENDING.

    Raises ``SyncInProgress`` if another ingestion already holds it. The check
    is here rather than in the UI because only the server can arbitrate: a
    client cannot know whether a PENDING row belongs to a live request or a
    dead one, and two clients cannot agree about it at all.
    """
    now = _now()
    source, created = _upsert(session, workspace_id, kind, external_ref)
    if not created and _holds_lease(source, now):
        raise SyncInProgress(external_ref, source.last_attempted_at)
    source.status = SyncStatus.PENDING
    source.last_attempted_at = now
    return source


def record_sync_success(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    external_ref: str,
    user_id: uuid.UUID | None = None,
    kind: str = GITHUB_KIND,
) -> DataSource:
    """Mark the attempt finished. ``last_attempted_at`` keeps the time the
    attempt *started*; ``last_synced_at`` is when the data actually landed."""
    source, _ = _upsert(session, workspace_id, kind, external_ref)
    source.status = SyncStatus.SUCCESS
    source.last_synced_at = _now()
    source.last_synced_by = user_id
    source.last_error = None
    return source


def record_sync_failure(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    external_ref: str,
    error: str,
    kind: str = GITHUB_KIND,
) -> DataSource:
    """Mark the attempt failed, leaving ``last_synced_at`` alone: the source may
    still be showing data from an earlier success, and the UI has to say so."""
    source, _ = _upsert(session, workspace_id, kind, external_ref)
    source.status = SyncStatus.FAILED
    source.last_error = error[:MAX_ERROR_LENGTH] or None
    return source


def list_synced_sources(
    session: Session, workspace_id: uuid.UUID
) -> list[SyncedSource]:
    """Every source connected to this workspace, ordered the way the graph
    query orders repositories (case-insensitively by name)."""
    rows = session.execute(
        select(DataSource, User.display_name, User.github_login)
        .outerjoin(User, User.id == DataSource.last_synced_by)
        .where(DataSource.workspace_id == workspace_id)
        .order_by(func.lower(DataSource.external_ref), DataSource.external_ref)
    ).all()

    # display_name, then the GitHub login, then nothing. Never the email: a
    # workspace is shared, and no other endpoint exposes a member's address.
    return [
        SyncedSource(source=source, last_synced_by_name=display_name or github_login)
        for source, display_name, github_login in rows
    ]


def build_source_inventory(
    synced: Iterable[SyncedSource],
    graph_summaries: Iterable[SourceSummaryPayload],
) -> list[SourceInventoryItem]:
    """Merge the relational source list with the graph's indexed counts.

    ``data_sources`` is authoritative for *which* sources are connected -- a
    repository whose ingestion failed has no graph nodes at all, and has to
    appear anyway (AC1). Neo4j stays authoritative for the counts.

    A repository ingested before this table existed has graph nodes and no row.
    It is reported as SUCCESS with unknown timestamps rather than dropped: the
    items are demonstrably indexed, we just do not know when. That makes the
    migration backfill-free.
    """
    counts = {summary.repo: summary for summary in graph_summaries}
    items: list[SourceInventoryItem] = []

    for entry in synced:
        source = entry.source
        summary = counts.pop(source.external_ref, None)
        items.append(
            SourceInventoryItem(
                repo=source.external_ref,
                kind=source.kind,
                status=source.status,
                pull_requests=summary.pull_requests if summary else 0,
                issues=summary.issues if summary else 0,
                total_items=summary.total_items if summary else 0,
                last_attempted_at=source.last_attempted_at,
                last_synced_at=source.last_synced_at,
                last_error=source.last_error,
                last_synced_by=source.last_synced_by,
                last_synced_by_name=entry.last_synced_by_name,
            )
        )

    for summary in counts.values():
        items.append(
            SourceInventoryItem(
                repo=summary.repo,
                kind=GITHUB_KIND,
                status=SyncStatus.SUCCESS,
                pull_requests=summary.pull_requests,
                issues=summary.issues,
                total_items=summary.total_items,
                last_attempted_at=None,
                last_synced_at=None,
                last_error=None,
                last_synced_by=None,
                last_synced_by_name=None,
            )
        )

    items.sort(key=lambda item: (item.repo.lower(), item.repo))
    return items
