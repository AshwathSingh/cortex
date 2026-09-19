# Cortex backend — local dev setup

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

Stop everything with `docker compose down` (data persists in named volumes; add
`-v` to also wipe them).

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
docker compose exec -T neo4j cypher-shell -u neo4j -p cortexgraph "SHOW CONSTRAINTS"
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
(`postgresql://cortex:cortex@localhost:5432/cortex`).

There's no schema yet — that's T-1.3 (Postgres schema for user profiles + GitHub
IDs, coordinated with Kuanyu on T-1.2) — so connectivity is all there is to test
for now.
