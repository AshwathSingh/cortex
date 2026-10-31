"""T-7.5 / T-8.1: the endpoints that trigger ingestion, one per provider.

    POST /api/ingest/github   {"repo_url": ..., "workspace_id": ...}

Each handler does three provider-specific things -- build the adapter, name the
source, shape the response -- and delegates the rest to
``app.sources.pipeline.run_ingestion``, which owns the order the sync record
(US-10) has to be written in. Mapping a provider failure onto an HTTP status is
the only part of that still here, because HTTP is this layer's concern and
nothing below it should know a status code.

The caller's role must carry ``sources.write``; ingestion writes nodes, so a
VIEWER (or any custom role without it) may not trigger it. That check runs
before any network or database call, so an unauthorised caller cannot use these
endpoints to reach a provider or spend the server's rate limit. The source
reference is validated next, and payloads are validated before the write
transaction, so a failed request creates no nodes.

A reference that does not parse is a 422 and records nothing: no real source was
identified, so there is nothing to record. Every failure after that point is
recorded against the source before the error leaves the handler.
"""

import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.config import settings
from app.db.neo4j_driver import get_driver
from app.github.client import GitHubClient
from app.models import User
from app.permissions import Permission
from app.services.data_sources import SyncInProgress
from app.sources.base import (
    InvalidSourceRef,
    SourceAdapter,
    SourceAPIError,
    SourceError,
    SourceNotFound,
    SourceRateLimited,
    SourceUnauthorized,
)
from app.sources.github import GitHubAdapter
from app.sources.pipeline import GraphUnavailable, IngestionOutcome, run_ingestion

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

# Ordered: the first match wins, so a subclass must precede its base. GitHub's
# RateLimitExceeded is both a SourceRateLimited and a SourceAPIError, which is
# why rate limiting is tested before the generic API failure.
ERROR_STATUS: tuple[tuple[type[SourceError], int], ...] = (
    (SourceNotFound, 404),
    (SourceRateLimited, 429),
    (SourceUnauthorized, 403),
    (GraphUnavailable, 503),
    (SourceAPIError, 502),
)


class IngestRequest(BaseModel):
    repo_url: str
    # Typed as UUID so a missing, null or malformed workspace is a 422 before any
    # work starts. The mapper re-checks it, for callers that bypass the API.
    workspace_id: uuid.UUID


class IngestResponse(BaseModel):
    repo: str
    pull_requests: int
    issues: int


def get_github_client() -> Iterator[GitHubClient]:
    client = GitHubClient(token=settings.github_token)
    try:
        yield client
    finally:
        client.close()


def get_neo4j() -> Driver:
    return get_driver()


def _http_error(adapter: SourceAdapter, error: SourceError) -> HTTPException:
    """The status and wording for a provider failure the pipeline re-raised."""
    detail = adapter.describe(error)
    headers = (
        {"Retry-After": str(int(error.wait_seconds))}
        if isinstance(error, SourceRateLimited)
        else None
    )
    for error_type, status_code in ERROR_STATUS:
        if isinstance(error, error_type):
            return HTTPException(
                status_code=status_code, detail=detail, headers=headers
            )
    # Unreachable while every SourceError subclasses one of the five above; a
    # new one defaults to "the provider misbehaved" rather than a 500.
    return HTTPException(status_code=502, detail=detail)


def _ingest(
    adapter: SourceAdapter,
    driver: Driver,
    session: Session,
    *,
    workspace_id: uuid.UUID,
    external_ref: str,
    user: User,
) -> IngestionOutcome:
    """Run the pipeline and translate its failures into HTTP."""
    try:
        return run_ingestion(
            adapter,
            driver,
            session,
            workspace_id=workspace_id,
            external_ref=external_ref,
            user_id=user.id,
        )
    except SyncInProgress:
        # Server-arbitrated: two ingestions of one source would race to write
        # its final status, and the second would re-spend the provider rate
        # limit the first is already using.
        raise HTTPException(
            status_code=409,
            detail=f"An ingestion of {external_ref} is already running",
        )
    except SourceError as error:
        raise _http_error(adapter, error)
    finally:
        adapter.close()


@router.post("/github", response_model=IngestResponse)
def ingest_github(
    body: IngestRequest,
    user: CurrentUser,
    session: DbSession,
    client: GitHubClient = Depends(get_github_client),
    driver: Driver = Depends(get_neo4j),
) -> IngestResponse:
    load_workspace_for_user(
        session, user, body.workspace_id, permission=Permission.SOURCES_WRITE
    )

    try:
        adapter = GitHubAdapter(client, body.repo_url)
    except InvalidSourceRef as e:
        raise HTTPException(status_code=422, detail=str(e))

    outcome = _ingest(
        adapter,
        driver,
        session,
        workspace_id=body.workspace_id,
        external_ref=adapter.external_ref,
        user=user,
    )
    return IngestResponse(
        repo=outcome.display_ref,
        pull_requests=outcome.counts.get("pull_requests", 0),
        issues=outcome.counts.get("issues", 0),
    )
