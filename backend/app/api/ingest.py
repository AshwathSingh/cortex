"""T-7.5: endpoint that triggers the GitHub ingestion pipeline.

    POST /api/ingest/github
    {"repo_url": "https://github.com/owner/repo", "workspace_id": "<uuid>"}

Pipeline: authorise the workspace -> parse URL -> fetch PRs/issues (T-7.3) ->
validate + write graph (T-7.4). Ingested nodes are stamped with
``workspace_id`` so the Graph Explorer (US-14) can filter by workspace.

The caller must hold OWNER or EDITOR on the workspace; ingestion writes nodes, so
a VIEWER may not trigger it. That check runs before any network or database call,
so an unauthorised caller cannot use this endpoint to reach GitHub or spend the
server's rate limit. The URL is validated next, and payloads are validated before
the write transaction, so a failed request creates no nodes.
"""

import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, ValidationError

from app.api.deps import WRITER_ROLES, CurrentUser, DbSession, load_workspace_for_user
from app.config import settings
from app.db.neo4j_driver import get_driver
from app.github.client import (
    GitHubAPIError,
    GitHubClient,
    InvalidRepoURL,
    RateLimitExceeded,
    RepoNotFound,
    parse_repo_url,
)
from app.github.mapper import write_graph

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


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


@router.post("/github", response_model=IngestResponse)
def ingest_github(
    body: IngestRequest,
    user: CurrentUser,
    session: DbSession,
    client: GitHubClient = Depends(get_github_client),
    driver: Driver = Depends(get_neo4j),
) -> IngestResponse:
    load_workspace_for_user(session, user, body.workspace_id, require=WRITER_ROLES)

    try:
        owner, name = parse_repo_url(body.repo_url)
    except InvalidRepoURL as e:
        raise HTTPException(status_code=422, detail=str(e))

    repo = f"{owner}/{name}"
    try:
        prs = list(client.iter_pull_requests(owner, name))
        issues = list(client.iter_issues(owner, name))
    except RepoNotFound:
        raise HTTPException(status_code=404, detail=f"Repository {repo} not found or not accessible")
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail="GitHub rate limit reached",
            headers={"Retry-After": str(int(e.wait_seconds))},
        )
    except GitHubAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        write_graph(driver, repo, prs, issues, workspace_id=body.workspace_id)
    except ValidationError:
        raise HTTPException(status_code=502, detail="GitHub returned an unexpected payload shape")
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    return IngestResponse(repo=repo, pull_requests=len(prs), issues=len(issues))
