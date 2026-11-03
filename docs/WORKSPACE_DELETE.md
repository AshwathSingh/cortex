# Deleting a workspace (US-05) — run and test

Run the backend as in [INVITES.md](INVITES.md), then apply the new migration: `alembic upgrade head`.

## Test

```bash
cd backend
python -m pytest tests/test_workspace_delete.py -q   # delete tests
python -m pytest -q                                   # everything (start Docker first)
```

## Try it

```bash
A=http://localhost:8000/api
# wrong name -> 400, nothing deleted
curl -s -b owner.jar -X DELETE $A/workspaces/<WORKSPACE_ID> \
  -H 'content-type: application/json' -d '{"confirm_name":"wrong"}' -w "\n%{http_code}\n"
# exact name (case-sensitive) -> 204
curl -s -b owner.jar -X DELETE $A/workspaces/<WORKSPACE_ID> \
  -H 'content-type: application/json' -d '{"confirm_name":"Demo"}' -w "%{http_code}\n"
```

## Rules

`DELETE /api/workspaces/{id}` with `{"confirm_name": "<exact name>"}` → 204

- Owner only (`workspace.delete`); anyone else gets 403 whatever they typed, and nothing is touched.
- Missing or wrong `confirm_name` → 400. Matching is exact: case-sensitive, no trimming.
- Order: mark `deleting` → delete graph nodes/edges in Neo4j (batches of 1000) → delete the Postgres row (members, invites, roles, data sources cascade).
- A workspace being deleted is hidden everywhere (403, like a workspace that doesn't exist) and can't receive new data: syncs and invite accepts in flight are refused.
- If a store fails part-way: 500, the workspace stays hidden, and sending the same request again finishes the job (the name is required again).
- Afterwards, former members get 403 on the workspace and its resources.
- GitHub tokens belong to users, not workspaces, so they are not deleted.
