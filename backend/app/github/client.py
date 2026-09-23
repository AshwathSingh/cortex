import re
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlparse

import httpx

API_BASE = "https://api.github.com"
PER_PAGE = 100


class InvalidRepoURL(ValueError):
    pass


class RepoNotFound(Exception):
    pass


class GitHubAPIError(Exception):
    pass


class RateLimitExceeded(GitHubAPIError):
    def __init__(self, wait_seconds: float):
        super().__init__(f"GitHub rate limit hit; would need to wait {wait_seconds:.0f}s")
        self.wait_seconds = wait_seconds


_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_repo_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in (
        "github.com",
        "www.github.com",
    ):
        raise InvalidRepoURL(f"Not a GitHub repository URL: {url!r}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise InvalidRepoURL(f"URL must include owner and repo: {url!r}")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not _SEGMENT.match(owner) or not _SEGMENT.match(repo):
        raise InvalidRepoURL(f"Invalid owner/repo in URL: {url!r}")
    return owner, repo


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        max_rate_limit_wait: float = 900,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=API_BASE, headers=headers, transport=transport, timeout=30
        )
        self._max_retries = max_retries
        self._max_wait = max_rate_limit_wait
        self._sleep = sleep
        self._now = now

    def close(self) -> None:
        self._http.close()

    def _rate_limit_wait(self, resp: httpx.Response) -> float | None:
        """Seconds to wait if this response is a rate-limit rejection, else None."""
        if resp.status_code not in (403, 429):
            return None
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            return float(retry_after)
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = float(resp.headers.get("X-RateLimit-Reset", 0))
            return max(reset - self._now(), 0) + 1
        return None

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            resp = self._http.get(url, params=params)
            wait = self._rate_limit_wait(resp)
            if wait is None:
                break
            if wait > self._max_wait or attempt == self._max_retries:
                raise RateLimitExceeded(wait)
            self._sleep(wait)
        if resp.status_code == 404:
            raise RepoNotFound(f"GitHub returned 404 for {url}")
        if resp.status_code >= 400:
            raise GitHubAPIError(f"GitHub returned {resp.status_code} for {url}")
        return resp

    def _paginate(self, path: str, params: dict) -> Iterator[dict]:
        url: str | None = path
        query: dict | None = {**params, "per_page": PER_PAGE}
        while url:
            resp = self._get(url, query)
            yield from resp.json()
            url = resp.links.get("next", {}).get("url")
            query = None  # the next-link URL already carries the query string

    def iter_pull_requests(self, owner: str, repo: str, state: str = "all") -> Iterator[dict]:
        return self._paginate(f"/repos/{owner}/{repo}/pulls", {"state": state})

    def iter_issues(self, owner: str, repo: str, state: str = "all") -> Iterator[dict]:
        # The issues endpoint also returns PRs; those carry a "pull_request" key.
        for item in self._paginate(f"/repos/{owner}/{repo}/issues", {"state": state}):
            if "pull_request" not in item:
                yield item

    def fetch_repo(self, repo_url: str) -> tuple[list[dict], list[dict]]:
        owner, repo = parse_repo_url(repo_url)
        prs = list(self.iter_pull_requests(owner, repo))
        issues = list(self.iter_issues(owner, repo))
        return prs, issues
