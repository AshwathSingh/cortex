# Removing members (US-04) — run and test

Run the backend as in [INVITES.md](INVITES.md). No new migration.

## Test

```bash
cd backend
python -m pytest tests/test_members_api.py -q   # removal tests
python -m pytest -q                              # everything (start Docker first)
```

## Try it

With an owner (`owner.jar`) and a guest who has accepted an invite (see INVITES.md):

```bash
A=http://localhost:8000/api
curl -s -b owner.jar -X DELETE $A/workspaces/<WORKSPACE_ID>/members/<GUEST_USER_ID> -w "%{http_code}\n"   # 204
curl -s -b guest.jar $A/workspaces/<WORKSPACE_ID>/members -w "%{http_code}\n"                            # 403, access gone
```

Find user ids with `GET /api/workspaces/{id}/members`.

## Rules

`DELETE /api/workspaces/{id}/members/{user_id}` → 204

- Needs `members.manage`, **except** anyone can remove themselves (leave the workspace).
- Only an owner can remove an owner.
- The last owner can't be removed and can't leave (409). Concurrent removals are safe: owner rows are locked.
- Not a member → 404. Not logged in → 401. No permission, or caller not in the workspace → 403.
- Pending invites the removed person sent are left in place.
- Access is checked against the database on every request (no caches, no JWT claims, no websockets in the app), so removal applies on their next request.
