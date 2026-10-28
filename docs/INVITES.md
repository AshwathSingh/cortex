# Workspace invites (US-03) — run and test

## Run the backend

```bash
docker compose up -d postgres neo4j      # databases
cd backend
source .venv/bin/activate                # first time: python -m venv .venv && pip install -r requirements.txt
alembic upgrade head                     # creates the invite tables
uvicorn app.main:app --reload            # http://localhost:8000/docs
```

Optional: `INVITE_TTL_DAYS` in `.env` sets how long an invite lasts (default 7).

## Run the tests

```bash
cd backend
python -m pytest -q                      # everything
python -m pytest tests/test_invites_api.py -q   # invites only
```

Tests that need Postgres or Neo4j are skipped if Docker isn't running, so start it first.

## Try it by hand

Two accounts are needed: an owner and a guest. Passwords must be 15+ characters.

```bash
A=http://localhost:8000/api
curl -s -X POST $A/auth/signup -H 'content-type: application/json' \
  -d '{"email":"owner@example.com","password":"owner-password-123"}'
curl -s -X POST $A/auth/signup -H 'content-type: application/json' \
  -d '{"email":"guest@example.com","password":"guest-password-123"}'

# 1. Owner logs in, creates a workspace, invites the guest
curl -s -c owner.jar -X POST $A/auth/login -H 'content-type: application/json' \
  -d '{"email":"owner@example.com","password":"owner-password-123"}'
curl -s -b owner.jar -X POST $A/workspaces -H 'content-type: application/json' \
  -d '{"name":"Demo"}'                              # copy the workspace "id"
curl -s -b owner.jar -X POST $A/workspaces/<WORKSPACE_ID>/invites \
  -H 'content-type: application/json' \
  -d '{"email":"guest@example.com","role":"VIEWER"}'  # copy the "token" (shown once)

# 2. Guest logs in and accepts
curl -s -c guest.jar -X POST $A/auth/login -H 'content-type: application/json' \
  -d '{"email":"guest@example.com","password":"guest-password-123"}'
curl -s -b guest.jar -X POST $A/invites/<TOKEN>/accept        # -> {"workspace_id":..., "role":"VIEWER"}
curl -s -b guest.jar $A/workspaces/<WORKSPACE_ID>/members     # guest can now see the workspace

# 3. Try the same token again -> 409
curl -s -b guest.jar -X POST $A/invites/<TOKEN>/accept
```

## Endpoints

| Call | Result |
| --- | --- |
| `POST /api/workspaces/{id}/invites` `{email, role?}` or `{email, role_id?}` | 201 `{id, email, role, role_id, expires_at, token}` |
| `POST /api/invites/{token}/accept` | 200 `{workspace_id, role}` |

Errors: 403 no permission to invite · 404 unknown token · 409 already a member, duplicate pending invite, or token already used/revoked · 410 token expired · 401 not logged in.

Notes: no email is sent, so share the token yourself. Any logged-in user holding the token can accept it, whatever their email.
