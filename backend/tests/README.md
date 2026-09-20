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
pytest -k rate_limit                      # only tests whose name matches
pytest -v                                 # list each test
```

These use `httpx.MockTransport` and a fake Neo4j driver, so they need no token,
internet or running database. They check the statements and parameters the
mapper builds, not the Cypher itself. For that, use the live check below.

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
