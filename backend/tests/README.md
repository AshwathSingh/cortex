# Running the backend tests

All commands run from `backend/` with the virtualenv active:

```
cd backend
source .venv/bin/activate      # first-time setup: see ../README.md
```

## Unit tests (no Docker, no network)

```
pytest                                    # everything
pytest tests/test_github_client.py        # GitHub REST client (T-7.3)
pytest tests/test_github_mapper.py        # payload validation + Cypher mapping (T-7.4)
pytest tests/test_ingest_api.py           # POST /api/ingest/github endpoint (T-7.5)
pytest -k rate_limit                      # only tests whose name matches
pytest -v                                 # list each test
```

The endpoint tests use FastAPI's `TestClient` with dependency overrides. All of them use `httpx.MockTransport` and a fake Neo4j driver, so they need no token,
internet or running database. They check the statements and parameters the
mapper builds, not the Cypher itself. For that, use the live check below.

### About the `StarletteDeprecationWarning`

Running the endpoint/integration tests prints:

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

`httpx2` is Pydantic's maintained continuation of `httpx` (a separate package —
`import httpx2` — that can be installed alongside plain `httpx`). Starlette's
`TestClient` now prefers it when present and only falls back to `httpx` with this
warning. Nothing is broken; the tests are fine to ignore this for now. Migrating would
mean adding `httpx2` to `requirements.txt` and swapping the `httpx.MockTransport` /
`httpx.Response` usages in `test_ingest_api.py` and `test_ingest_integration.py` to
their `httpx2` equivalents — not done yet, tracked as a follow-up.

## Integration tests (automated, needs Neo4j; T-7.7)

`tests/test_ingest_integration.py` runs mock GitHub payloads through the real
FastAPI endpoint, mapper and a real Neo4j. Only GitHub is mocked.

```
docker compose up -d neo4j          # from the repo root
pytest -m integration               # only these
pytest -m "not integration"         # everything except these (no Docker needed)
pytest                              # all; integration tests skip if Neo4j is down
```

They cover the US-7 acceptance criteria that exist today: valid repo builds the graph
(including pagination and PRs echoed by the issues API), invalid URL / 404 / rate limit /
malformed payload create **zero nodes**, re-ingest is idempotent and updates changed
fields, a failed re-ingest leaves the graph intact, and the T-7.2 uniqueness constraints
reject duplicate ids.

**Your data is safe.** Neo4j Community has a single database, so there is no separate
test database. Tests only create nodes with ids >= 9,000,000,000,000 and repos starting
with `cortex-test/`, and delete only those, before and after each test. Anything else in
the graph is never touched. Payload factories are in `tests/payloads.py`; the graph
fixtures are in `tests/conftest.py`.

## Live check against a real Neo4j (manual)

Verifies the Cypher, the `AUTHORED` edges, idempotency and that invalid payloads
write nothing. **It deletes every node in the target database**, so use only the
local dev container. The script aborts if the database is not empty.

1. Start Docker Desktop, then Neo4j from the repo root:

   ```
   docker compose up -d neo4j
   docker compose ps                       # neo4j should be "Up"
   ```

2. Apply the schema constraints (safe to re-run):

   ```
   python -m scripts.init_graph_schema
   ```

   Credentials come from the repo-root `.env`, whichever directory you run from.
   If you get `AuthError`, the password in `.env` doesn't match the one the
   container was first created with. Wipe the volume with
   `docker compose down -v` and start again (README step 3).

3. Save this as `live_check.py` (anywhere; don't commit it) and run it with
   `PYTHONPATH=. python live_check.py` from `backend/`:

   ```python
   from app.db.neo4j_driver import get_driver
   from app.github.mapper import write_graph

   U = {"id": 7, "login": "octocat", "html_url": "https://github.com/octocat"}
   pr = {"id": 100, "number": 1, "title": "Add", "state": "closed", "body": None,
         "html_url": "u", "created_at": "2024-01-01T00:00:00Z",
         "updated_at": "2024-01-02T00:00:00Z", "merged_at": "2024-01-02T00:00:00Z", "user": U}
   issue = {"id": 200, "number": 2, "title": "Bug", "state": "open", "body": "x",
            "html_url": "u2", "created_at": "2024-01-03T00:00:00Z",
            "updated_at": "2024-01-03T00:00:00Z", "user": U}
   ghost = {**issue, "id": 201, "number": 3, "user": None}   # deleted account

   d = get_driver()

   def one(cypher):
       with d.session() as s:
           return s.run(cypher).single()[0]

   def counts():
       nodes = {k: one(f"MATCH (n:{k}) RETURN count(n)")
                for k in ("Author", "PullRequest", "Issue")}
       return nodes, one("MATCH ()-[r:AUTHORED]->() RETURN count(r)")

   assert one("MATCH (n) RETURN count(n)") == 0, "DB not empty; aborting"
   write_graph(d, "o/r", [pr], [issue, ghost]); print("first ", counts())
   write_graph(d, "o/r", [pr], [issue, ghost]); print("rerun ", counts())
   try:
       write_graph(d, "o/r", [{**pr, "id": "bad"}], [])
   except Exception as e:
       print("invalid ->", type(e).__name__)
   print("after invalid", counts())
   d.execute_query("MATCH (n) DETACH DELETE n")              # clean up
   ```

   Expected output:

   ```
   first  ({'Author': 1, 'PullRequest': 1, 'Issue': 2}, 2)
   rerun  ({'Author': 1, 'PullRequest': 1, 'Issue': 2}, 2)
   invalid -> ValidationError
   after invalid ({'Author': 1, 'PullRequest': 1, 'Issue': 2}, 2)
   ```

   The rerun is unchanged (idempotent), and the invalid payload changes nothing.
   The author-less issue gets a node but no edge, hence 3 items and 2 edges.

To inspect the graph yourself, open http://localhost:7474 (credentials from
`.env`) and run `MATCH (n) RETURN n` before the cleanup line.

## End-to-end check of the ingest endpoint (manual, T-7.5)

Runs the real server against real GitHub and your local Neo4j. Use it to confirm
the whole pipeline (fetch, validate, write) with real data.

**Before you start**
- Docker up, Neo4j running, schema applied (steps 1 and 2 of the live check above).
- Unauthenticated GitHub allows only **60 requests/hour** (100 items per request).
  Pick a small public repo (under about 100 PRs/issues). A huge repo such as
  `octocat/Hello-World` exhausts the limit and the request will hang waiting for
  the reset. For larger repos, set `GITHUB_TOKEN=<personal access token>` in the
  repo-root `.env` (5,000 requests/hour). Check what you have left with:
  `curl -s https://api.github.com/rate_limit | grep -m1 remaining`
- Check the database is empty, or that you don't mind extra nodes. Ingest does
  not delete anything.

**1. Start the server** (from `backend/`, venv active)

```
uvicorn app.main:app --port 8000
curl localhost:8000/health              # {"status":"ok"}
```

**2. Call the endpoint** (in a second terminal)

```
curl -X POST localhost:8000/api/ingest/github \
  -H 'Content-Type: application/json' \
  -d '{"repo_url": "https://github.com/Vasu7389/react-project-ideas"}'
```

Expected: HTTP 200 and `{"repo":"Vasu7389/react-project-ideas","pull_requests":30,"issues":6}`
(counts reflect the repo at the time). Interactive docs: http://localhost:8000/docs.

**3. Inspect the graph**

In http://localhost:7474 (credentials from `.env`):

```
MATCH (n) RETURN n                                             // see it
MATCH (n) RETURN labels(n)[0] AS label, count(n)               // counts per label
MATCH ()-[r:AUTHORED]->() RETURN count(r)                      // edges
MATCH (n) WHERE (n:PullRequest OR n:Issue)
  AND NOT ()-[:AUTHORED]->(n) RETURN count(n)                  // should be 0
```

Expected for the repo above: 28 Authors, 30 PullRequests, 6 Issues, 36 edges.

**4. Check the failure paths**

| Request | Expected | Nodes created |
|---|---|---|
| Same repo again | 200, same counts (idempotent) | none new |
| `{"repo_url": "https://gitlab.com/a/b"}` | 422 | none |
| `{}` (no `repo_url`) | 422 | none |
| `{"repo_url": "https://github.com/ranadep/does-not-exist-xyz"}` | 404 | none |
| Stop Neo4j (`docker compose stop neo4j`), then a valid repo | 503 | none |

A repo with zero PRs and issues returns 200 with zeros and writes nothing.

**5. Clean up**

Stop the server with Ctrl+C. To empty the local graph (dev database only):

```
docker compose exec -T neo4j sh -c 'cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "MATCH (n) DETACH DELETE n"'
```
