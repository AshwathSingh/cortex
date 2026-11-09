# Ingestion failures (US-12) — run and test

Run the backend as in [INVITES.md](INVITES.md), then apply the new migration: `alembic upgrade head`.

## Test

```bash
cd backend
python -m pytest tests/test_source_failures.py -q    # categories and the endpoint
python -m pytest tests/test_reingest_dedup.py -q     # re-ingest dedup (needs Neo4j)
python -m pytest -q                                  # everything (start Docker first)
```

```bash
cd apps/web
npx vitest run src/components/sources/source-failures.test.tsx src/lib/use-source-failures.test.tsx
```

## Try it

```bash
A=http://localhost:8000/api
# break a source: an unreadable repo records a NOT_FOUND failure
curl -s -b owner.jar -X POST $A/ingest/github -H 'content-type: application/json' \
  -d '{"repo_url":"https://github.com/does-not/exist","workspace_id":"<WORKSPACE_ID>"}' \
  -w "\n%{http_code}\n"
# what is broken, and how to fix each one
curl -s -b owner.jar $A/workspaces/<WORKSPACE_ID>/source-failures | jq
```

## Rules

`GET /api/workspaces/{id}/source-failures` → the sources whose last ingestion failed,
newest attempt first. Any member may read it; it never touches Neo4j, so a graph
outage can still be reported.

Each row carries a `category` and the two decisions the UI makes from it:

| Category | Means | `needs_reauth` | `can_retry` |
| --- | --- | --- | --- |
| `AUTH` | token expired or revoked | yes | no — the same credentials fail the same way |
| `NOT_FOUND` | repo gone, renamed, or private to this token | yes | yes |
| `RATE_LIMIT` | GitHub is throttling this workspace | no | yes |
| `UPSTREAM` | GitHub 5xx, or a payload we cannot read | no | yes |
| `GRAPH` | Neo4j would not take the write | no | yes |
| `UNKNOWN` | recorded before the category existed | no | yes |

- The notice lives in the workspace shell, so a broken source is reported on every
  page, not just Sources (AC1).
- Nothing dismisses it: the list is derived from FAILED rows, so a successful sync
  clears it (AC3).
- A failing source keeps reporting its last *successful* sync, because the graph is
  still showing that data and how stale it is matters (AC4).

## Re-ingesting cleanly (T-12.3)

Every ingestion stamps `ingest_run` on what it writes and then, in the same
transaction, deletes what it did not: items removed upstream, `AUTHORED` edges from
a previous author, and authors with no work left anywhere in the workspace. One
transaction, so a failed or partial fetch deletes nothing — a half-read repository
looks exactly like one whose items were all deleted, and acting on that would
destroy live data.
