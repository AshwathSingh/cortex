# Cortex backend — local dev setup

Note:

1. Use python 3.13 or lower, some packages in the requirements.txt are not supported in 3.14
2. Rust is required for watchfile installation

## 1. Start Docker

```
open -a Docker              # if Docker Desktop isn't already running
```

Wait for the whale icon in the menu bar to show it's ready (or `docker info` will
succeed once it is).

## 2. Configure environment

From the repo root:

```
cp .env.example .env
```

`.env` holds local secrets (DB credentials, GitHub OAuth keys) and is gitignored —
never commit it.

## 3. Start Postgres + Neo4j

From the repo root:

```
docker compose up -d postgres neo4j
docker compose ps            # confirm both are "Up"
```

In the case where you already have an neo4j container, run this command instead.

```
docker compose up -d --force-recreate neo4j
```

Stop everything with `docker compose down` (data persists in named volumes; add
`-v` to also wipe them, you need to wipe your auth credentials from the docker everytime you changes the username and passwords in .env since docker will save these data from the very first instance).

## 4. Install backend Python deps

```
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 5. Initialize the Neo4j graph schema (T-7.1 / T-7.2)

```
python -m scripts.init_graph_schema
```

Applies uniqueness constraints for `Author.id`, `PullRequest.id`, `Issue.id`.
Safe to re-run (`IF NOT EXISTS`).

Verify:

```
docker compose exec -T neo4j sh -c 'cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "SHOW CONSTRAINTS"'
```

This reads the credentials from inside the `neo4j` container (which Compose fills in
from your `.env`), so it works with whatever user/password you set — no need to type
them, and no need to hardcode `neo4j`/`cortexgraph`. Note it's single-quoted: if you
instead run `cypher-shell -u "$NEO4J_USER" ...` directly (outside `sh -c '...'`), those
variables come from _your own shell's_ environment, not `.env`, and will be empty
unless you've separately exported them (e.g. `set -a && source .env && set +a`).

Neo4j browser UI: <http://localhost:7474> (user/password from `.env`).

## 6. Test Postgres connectivity

Quick readiness check:

```
docker compose exec -T postgres pg_isready -U cortex -d cortex
```

Run a query via `psql` inside the container:

```
docker compose exec -T postgres psql -U cortex -d cortex -c "SELECT version();"
```

Or drop into an interactive shell:

```
docker compose exec postgres psql -U cortex -d cortex
```

From Python/FastAPI, connect using `DATABASE_URL` from `.env`
(`postgresql+psycopg://cortex:cortex@localhost:5432/cortex`).

Apply the relational schema through the project preflight wrapper:

```
python -m scripts.init_postgres_schema
```

The wrapper detects databases created by the older `create_all` bootstrap before
running Alembic. If it reports a legacy schema, back up anything you need and reset
only the local Postgres schema before retrying:

```
docker compose exec -T postgres psql -U cortex -d cortex \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
python -m scripts.init_postgres_schema
```

The migrations create `users`, `workspaces`, `workspace_memberships`, and
`user_sessions`. Passwords and session tokens are stored only as hashes.

Verify:

```
docker compose exec -T postgres psql -U cortex -d cortex -c "\dt"
```

## 8. Create workspaces locally (US-41)

Signed-in users create workspaces through the API (`POST /api/workspaces`,
US-2; see step 9) or the web app's **New workspace** page. This script is for
seeding test data: it talks to Postgres directly, so it works whether or not the
API is running.

`trial` adds the scenario that exercises every US-41 acceptance criterion --
two users, four workspaces, five memberships -- and prints the curl commands
to check them, with the ids already filled in:

```
python -m scripts.dev_workspace trial
```

**`trial` only adds. `--reset` only deletes.** They are separate operations and
neither does the other's job. To start from empty:

```
python -m scripts.dev_workspace --reset     # deletes all users, workspaces, memberships
python -m scripts.dev_workspace trial       # adds the scenario back (2 users, 4 workspaces and 5 memberships)
```

Running `trial` on top of an existing trial is refused by the unique constraint
on the trial users -- nothing is deleted or half-written, so re-run `--reset`
first.

Building rows by hand instead:

```
python -m scripts.dev_workspace create-user --github-id 1001 --name "You" --email you@example.com --password "local-development-password"
python -m scripts.dev_workspace create-workspace --owner <user-id> --name "Cortex"
python -m scripts.dev_workspace add-member --workspace <ws-id> --user <user-id> --role VIEWER
python -m scripts.dev_workspace list
```

## 9. Run the API

Once you have initialized the postgres schema, created some users (either via `trial` or you did it yourself), you can run:

```
uvicorn app.main:app --reload
```

to start the server.

Email/password authentication uses an HttpOnly, SameSite session cookie. Session
tokens are hashed in Postgres and can be revoked through logout. Set
`SECURE_COOKIES=true` outside local HTTP development.

```
curl -c /tmp/cortex.cookies -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"local-development-password"}' \
  http://127.0.0.1:8000/api/auth/login
curl -b /tmp/cortex.cookies http://127.0.0.1:8000/api/workspaces
```

The curl commands after running `trial` will give you a more detailed breakdown.

Create a workspace (US-2). The caller becomes its `OWNER`; `description` is
optional. Names are 1–100 characters, descriptions up to 1000. A name the caller
already owns (case-insensitive) returns `409`, and invalid input returns `422`.

```
curl -b /tmp/cortex.cookies -H "Content-Type: application/json" \
  -d '{"name":"Apollo","description":"Launch plans"}' \
  http://127.0.0.1:8000/api/workspaces
```

A workspace the caller holds no role on returns `403`, and so does a workspace
id that does not exist — the two are deliberately indistinguishable so nobody
can probe which ids are real.

Verify the Postgres connection at <http://localhost:8000/api/health/database>.
