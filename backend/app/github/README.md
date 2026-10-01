# GitHub backend API (`app.github`)

Python interface for fetching a repository's pull requests and issues from the
GitHub REST API. Source: [client.py](client.py). Tests: [../../tests/test_github_client.py](../../tests/test_github_client.py).

> **Status:** this is an in-process Python client. The HTTP trigger is
> `POST /api/ingest/github` (T-7.5, [../api/ingest.py](../api/ingest.py)); see
> "HTTP endpoint" at the bottom.

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

## HTTP endpoint (T-7.5)

Requires an authenticated session cookie and **OWNER or EDITOR** on the target
workspace — ingestion writes nodes, so a VIEWER cannot trigger it.

```
cd backend && uvicorn app.main:app --reload
curl -X POST localhost:8000/api/ingest/github \
  -H 'Content-Type: application/json' \
  -b 'cortex_session=<token>' \
  -d '{"repo_url": "https://github.com/octocat/Hello-World",
       "workspace_id": "3f1c…"}'
# {"repo":"octocat/Hello-World","pull_requests":N,"issues":M}
```

| Status | Cause |
|---|---|
| 200 | Fetched, validated and written. Body: `repo`, `pull_requests`, `issues` counts. |
| 401 | No session cookie, or an expired/invalid one. |
| 403 | Caller holds no role on the workspace, or only VIEWER. Same 403 for a workspace that doesn't exist, so existence isn't leaked. |
| 422 | Invalid repo URL, or missing/malformed `repo_url` or `workspace_id`. Nothing fetched or written. |
| 404 | Repo not found or not accessible. |
| 429 | GitHub rate limit; `Retry-After` header set. |
| 502 | GitHub error or unexpected payload shape. Nothing written. |
| 503 | Neo4j unavailable. |

Authorization is checked **before** the URL is parsed and before any GitHub call,
so the endpoint can't be used to probe repositories or spend the server's rate
limit. The GitHub token is optional server config (`GITHUB_TOKEN` in `.env`) and is
never read from the request or returned. Interactive docs:
http://localhost:8000/docs. The call is synchronous: it returns after the whole
repo is ingested.

The frontend reaches this from `/workspaces/[workspaceId]/ingest`, which supplies
`workspace_id` from the route.

## Workspace scoping

Every node written carries a `workspace_id` property, and it is part of the MERGE
key for all three labels, so `(id, workspace_id)` — not `id` — identifies a node.
Two workspaces ingesting the same repo therefore get **separate copies** rather
than fighting over one shared node, and the `AUTHORED` MATCH is
workspace-qualified so an edge can never bind to another workspace's author. This
is what US-14's Graph Explorer filters on.

`app.github.mapper.normalise_workspace_id` rejects a missing, blank or non-UUID
workspace id before any statement is built, and canonicalises the UUID so two
spellings of one id can't create duplicate nodes. That guard matters because
Neo4j Community has no existence constraints — the database cannot reject an
unscoped node itself, and an unscoped node is invisible to every workspace query.

Nodes ingested before this change carry no `workspace_id`. They cannot be
backfilled (nothing records which workspace a repo belonged to), so wipe the
graph and re-ingest: `docker compose down -v`, then
`python -m scripts.init_graph_schema`.

## Running the tests

```
cd backend
pytest tests/test_github_client.py
```

Tests use `httpx.MockTransport`, so no network or token is needed.

## Not yet built

- **Background ingestion job.** `POST /api/ingest/github` is synchronous: it holds the
  HTTP request open until the whole repo is fetched and written. Large repos, or
  unauthenticated calls that hit GitHub's 60 requests/hour limit, can keep the request
  waiting for many minutes (the client waits up to 15 minutes for a rate-limit reset),
  which risks browser and proxy timeouts. Planned fix: return `202 Accepted` with a job
  id, run the ingestion in the background, and add a status endpoint (for example
  `GET /api/ingest/jobs/{id}` with `pending`/`running`/`done`/`failed`, counts and any
  error) that the frontend form polls. Until then, set `GITHUB_TOKEN` and ingest small
  repos.
- Auto-populating new issues during a live session (US-7 acceptance criterion).
- **Persisting the connected source.** Ingestion is still fire-and-forget: nothing
  records that a repo was connected to a workspace, so there is no repo list, no
  re-sync and no `last_synced_at`. US-10's `DataSource` table (carrying
  `workspace_id`) is the intended home. Deliberately deferred — no current
  consumer reads it, and the request shape above already takes `workspace_id`, so
  adding it later needs no API change.
- Token handling: `GITHUB_CLIENT_ID`/`SECRET` are in `.env.example`, but the
  client takes a plain token argument. OAuth (US-1) must supply it, and tokens
  must be decrypted only in-process and never returned in API responses.
