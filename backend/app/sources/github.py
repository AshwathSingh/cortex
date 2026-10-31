"""T-8.1: US-7's GitHub ingestion, behind the shared adapter contract.

Nothing about *how* GitHub is read changed here -- the client still paginates
pulls and issues, the mapper still writes the same four labels. This is the
wrapper that lets the endpoint stop importing either of them directly.

The repository URL is parsed in ``__init__`` rather than in ``fetch`` on
purpose: the pipeline takes the ``data_sources`` lease on ``external_ref``
*before* calling ``fetch``, so the reference has to exist before any network
call, and a URL that does not parse must fail as a 422 with no sync row written
(there is no real source to record).
"""

import uuid
from typing import ClassVar

from neo4j import Driver

from app.github.client import GitHubClient, parse_repo_url
from app.github.mapper import write_graph
from app.sources.base import (
    KIND_GITHUB,
    FetchedSource,
    SourceAdapter,
    SourceError,
    SourceNotFound,
    SourceRateLimited,
)


class GitHubAdapter(SourceAdapter):
    kind: ClassVar[str] = KIND_GITHUB

    def __init__(self, client: GitHubClient, repo_url: str):
        """Raises ``InvalidRepoURL`` for a URL this provider cannot parse."""
        self._client = client
        self._owner, self._name = parse_repo_url(repo_url)

    @property
    def external_ref(self) -> str:
        return f"{self._owner}/{self._name}"

    def fetch(self) -> FetchedSource:
        pulls = list(self._client.iter_pull_requests(self._owner, self._name))
        issues = list(self._client.iter_issues(self._owner, self._name))
        return FetchedSource(
            external_ref=self.external_ref,
            display_ref=self.external_ref,
            counts={"pull_requests": len(pulls), "issues": len(issues)},
            payloads={"pull_requests": pulls, "issues": issues},
        )

    def write(
        self,
        driver: Driver,
        fetched: FetchedSource,
        *,
        workspace_id: str | uuid.UUID,
    ) -> None:
        write_graph(
            driver,
            fetched.external_ref,
            fetched.payloads["pull_requests"],
            fetched.payloads["issues"],
            workspace_id=workspace_id,
        )

    # No close() override on purpose: the GitHub client is injected by a FastAPI
    # dependency that owns its lifetime (US-7's ``get_github_client``), so
    # closing it here would shut down a client the caller may still be using.
    # The chat adapters build their own and do close them.

    def describe(self, error: SourceError) -> str:
        # SourceRateLimited first: RateLimitExceeded is also a GitHubAPIError, so
        # testing the API error first would swallow it.
        if isinstance(error, SourceRateLimited):
            return "GitHub rate limit reached"
        if isinstance(error, SourceNotFound):
            return f"Repository {self.external_ref} not found or not accessible"
        return str(error)
