"""T-7.5: endpoint that triggers the GitHub ingestion pipeline.

    POST /api/ingest/github   {"repo_url": "https://github.com/owner/repo"}

Pipeline: parse URL -> fetch PRs/issues (T-7.3) -> validate + write graph (T-7.4).
The URL is validated before any network or database call, and payloads are
validated before the write transaction, so a failed request creates no nodes.
"""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, ValidationError

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
    client: GitHubClient = Depends(get_github_client),
    driver: Driver = Depends(get_neo4j),
) -> IngestResponse:
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
        write_graph(driver, repo, prs, issues)
    except ValidationError:
        raise HTTPException(status_code=502, detail="GitHub returned an unexpected payload shape")
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    return IngestResponse(repo=repo, pull_requests=len(prs), issues=len(issues))
