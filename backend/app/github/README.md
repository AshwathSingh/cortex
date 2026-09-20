# GitHub backend API (`app.github`)

Python interface for fetching a repository's pull requests and issues from the
GitHub REST API. Source: [client.py](client.py). Tests: [../../tests/test_github_client.py](../../tests/test_github_client.py).

> **Status:** this is an in-process Python client, not an HTTP endpoint. There is
> no FastAPI route for it yet — the trigger endpoint is T-7.5. Until then, call it
> from Python as shown below.

It returns **raw GitHub JSON** (`dict`s). Pydantic normalization and Cypher
mapping happen downstream (T-7.4); nothing here writes to Neo4j.

## Setup

```
cd backend
source .venv/bin/activate      # see ../../README.md for env setup
```

Dependencies: `httpx` (see `requirements.txt`). No env vars are required. An
optional GitHub token raises the rate limit (60 req/hr unauthenticated vs
5,000 req/hr authenticated).

## Quick start

```python
from app.github.client import GitHubClient

client = GitHubClient(token=None)   # or a GitHub token string
try:
    prs, issues = client.fetch_repo("https://github.com/octocat/Hello-World")
finally:
    client.close()
```

`fetch_repo` returns `(pull_requests, issues)`, each a `list[dict]` covering all
states (open and closed), all pages.

## Reference

### `parse_repo_url(url: str) -> tuple[str, str]`

Returns `(owner, repo)`. Accepts `http`/`https` URLs on `github.com` or
`www.github.com`, with an optional trailing slash, `.git` suffix, or extra path
segments.

| Input | Result |
|---|---|
| `https://github.com/octo/cat` | `("octo", "cat")` |
| `https://github.com/octo/cat.git` | `("octo", "cat")` |
| `https://github.com/octo/cat/pulls` | `("octo", "cat")` |
| `https://gitlab.com/a/b`, `ftp://github.com/a/b`, `https://github.com/onlyowner`, `""` | raises `InvalidRepoURL` |

Validation happens before any network call, so an invalid URL never reaches
GitHub (and, downstream, never creates Neo4j nodes).

### `GitHubClient(token=None, *, max_retries=3, max_rate_limit_wait=900, ...)`

| Argument | Default | Meaning |
|---|---|---|
| `token` | `None` | GitHub token, sent as `Authorization: Bearer <token>`. |
| `max_retries` | `3` | Rate-limit retries per request before giving up. |
| `max_rate_limit_wait` | `900` | Longest single wait (seconds) the client will sleep for. |
| `transport` | `None` | `httpx` transport override — use `httpx.MockTransport` in tests. |
| `sleep`, `now` | `time.sleep`, `time.time` | Injectable for tests. |

Requests use `Accept: application/vnd.github+json`, API version `2022-11-28`,
100 items per page, 30 s timeout.

### Methods

| Method | Returns | Notes |
|---|---|---|
| `fetch_repo(repo_url)` | `(list[dict], list[dict])` | Parses the URL, then fetches all PRs and all issues. Eager; loads everything into memory. |
| `iter_pull_requests(owner, repo, state="all")` | `Iterator[dict]` | Lazy. `state`: `open`, `closed`, or `all`. |
| `iter_issues(owner, repo, state="all")` | `Iterator[dict]` | Lazy. Filters out pull requests (GitHub's issues endpoint returns both). |
| `close()` | `None` | Closes the underlying HTTP connection. |

Pagination follows GitHub's `Link: rel="next"` header until exhausted.

Endpoints called: `GET /repos/{owner}/{repo}/pulls` and
`GET /repos/{owner}/{repo}/issues`.

## Rate limiting

A `403`/`429` response is treated as a rate-limit rejection when it carries a
`Retry-After` header or `X-RateLimit-Remaining: 0`. The client then:

1. Waits `Retry-After` seconds, or until `X-RateLimit-Reset` + 1 s.
2. Retries, up to `max_retries` times.
3. Raises `RateLimitExceeded` if the required wait exceeds `max_rate_limit_wait`
   or retries run out. `exc.wait_seconds` tells the caller how long the reset is.

A `403` with neither header is **not** retried and surfaces as `GitHubAPIError`.

## Errors

| Exception | Raised when | Suggested HTTP mapping (T-7.5) |
|---|---|---|
| `InvalidRepoURL` (`ValueError`) | URL isn't a valid GitHub repo URL | `422` / `400` |
| `RepoNotFound` | GitHub returns `404` (missing or private repo without access) | `404` |
| `RateLimitExceeded` (`GitHubAPIError`) | Rate limit hit and wait too long or retries exhausted | `429` with `Retry-After` |
| `GitHubAPIError` | Any other GitHub status `>= 400` | `502` |

## Fields the mapper will rely on

Objects are passed through untouched, so all GitHub fields are present.
Commonly needed: `number`, `title`, `state`, `body`, `user` (`id`, `login`),
`created_at`, `updated_at`, `html_url` (provenance link to the source). PRs
additionally have `merged_at`, `head`, and `base`.

## Running the tests

```
cd backend
pytest tests/test_github_client.py
```

Tests use `httpx.MockTransport`, so no network or token is needed.

## Not yet built

- HTTP endpoint to trigger ingestion (T-7.5).
- Pydantic normalization and Cypher mapping (T-7.4).
- Token handling: `GITHUB_CLIENT_ID`/`SECRET` are in `.env.example`, but the
  client takes a plain token argument. OAuth (US-1) must supply it, and tokens
  must be decrypted only in-process and never returned in API responses.
