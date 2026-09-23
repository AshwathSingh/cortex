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
set -a
source ../.env
set +a
docker compose exec -T neo4j /var/lib/neo4j/bin/cypher-shell \
  -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" "SHOW CONSTRAINTS"
```

Neo4j browser UI: http://localhost:7474 (user/password from `.env`).

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

Apply the relational schema:

```
alembic upgrade head
```

`alembic upgrade head` applies all pending migrations so your local Postgres
schema matches the latest application models.

The first migration creates `users` for email/password and GitHub-linked
accounts. Passwords must only be stored as hashes; sessions and OAuth tokens
will use separate tables when those workflows are implemented.
