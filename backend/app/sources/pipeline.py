"""T-8.1: the ingestion sequence every provider shares.

US-7 ran this inline in the GitHub endpoint and US-10 threaded the sync record
through it. Both are here now, once, so Slack and Discord inherit the lease, the
"Syncing…" window and the failure bookkeeping rather than reimplementing them.

The order matters and is the whole reason this is a function rather than three
endpoints calling three helpers:

    record_sync_attempt   PENDING, committed *before* the fetch
    adapter.fetch         minutes, over someone else's network
    adapter.write         one transaction, all-or-nothing
    record_sync_success   SUCCESS, or record_sync_failure on any exit above

A failure is recorded and committed before the error leaves this function,
because a failed ingestion writes nothing to the graph -- that row is the only
evidence the source was ever connected, and the only thing that can render a red
"Needs attention" against it.

HTTP lives in ``app.api.ingest``. This module raises the ``Source*`` errors the
adapter raised, so nothing here has to know which status code each one becomes.
"""

import uuid
from dataclasses import dataclass

from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.sources.base import FetchedSource, SourceAdapter, SourceAPIError, SourceError
from app.services.data_sources import (
    record_sync_attempt,
    record_sync_failure,
    record_sync_success,
)


class GraphUnavailable(SourceError):
    """Neo4j refused the write. Separate from ``SourceAPIError`` because the
    provider was fine -- retrying the same ingestion later is the right move, so
    the API answers 503 rather than 502."""


@dataclass(frozen=True)
class IngestionOutcome:
    external_ref: str
    display_ref: str
    counts: dict[str, int]


def _fail(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    external_ref: str,
    kind: str,
    detail: str,
) -> None:
    record_sync_failure(
        session,
        workspace_id=workspace_id,
        external_ref=external_ref,
        error=detail,
        kind=kind,
    )
    session.commit()


def run_ingestion(
    adapter: SourceAdapter,
    driver: Driver,
    session: Session,
    *,
    workspace_id: uuid.UUID,
    external_ref: str,
    user_id: uuid.UUID | None = None,
) -> IngestionOutcome:
    """Fetch one source and write it to the graph, keeping its sync row in step.

    ``external_ref`` is passed in rather than read off the fetch result: the
    lease has to be taken before the fetch starts, so the reference must be known
    before the adapter has read anything. An adapter may return a *different*
    ref from ``fetch`` -- Slack reports the team id it actually authenticated as
    -- in which case the sync row for the ref we leased is the one that gets the
    outcome, and the caller sees the resolved ref in the response.

    Raises ``SyncInProgress`` (the lease is held), ``GraphUnavailable``, or
    whatever ``Source*`` error the adapter raised. Every one of those paths has
    already recorded and committed the failure, except ``SyncInProgress``, which
    is not this request's failure to record.
    """
    record_sync_attempt(
        session,
        workspace_id=workspace_id,
        external_ref=external_ref,
        kind=adapter.kind,
    )
    session.commit()

    try:
        fetched: FetchedSource = adapter.fetch()
    except SourceError as error:
        _fail(
            session,
            workspace_id=workspace_id,
            external_ref=external_ref,
            kind=adapter.kind,
            detail=adapter.describe(error),
        )
        raise

    try:
        adapter.write(driver, fetched, workspace_id=workspace_id)
    except ValidationError as error:
        detail = f"{adapter.kind} returned an unexpected payload shape"
        _fail(
            session,
            workspace_id=workspace_id,
            external_ref=external_ref,
            kind=adapter.kind,
            detail=detail,
        )
        raise SourceAPIError(detail) from error
    except (Neo4jError, DriverError) as error:
        detail = "Graph database unavailable"
        _fail(
            session,
            workspace_id=workspace_id,
            external_ref=external_ref,
            kind=adapter.kind,
            detail=detail,
        )
        raise GraphUnavailable(detail) from error

    record_sync_success(
        session,
        workspace_id=workspace_id,
        external_ref=external_ref,
        user_id=user_id,
        kind=adapter.kind,
    )
    session.commit()
    return IngestionOutcome(
        external_ref=fetched.external_ref,
        display_ref=fetched.display_ref,
        counts=fetched.counts,
    )
