# Cortex

**Auditable project memory for development teams.**

Cortex ingests your project's scattered context (GitHub pull requests and issues, Slack decisions, PRDs) and turns it into a structured, queryable **knowledge graph**. Every node and every edge links back to the raw evidence that produced it, so you can always answer _"why do we believe this?"_

> CS 407 Senior Project · Purdue University

---

## The problem

Decisions get made in Slack threads, argued over in pull requests, and written down (eventually) in a PRD. Months later nobody remembers which one won. Teams end up:

- acting on **contradictory decisions** made on different platforms,
- **repeating mistakes** that were already resolved, and
- asking LLM coding agents for help when those agents have no idea what the team already decided.

Wikis and issue trackers don't fix this because they aren't a single source of truth. General AI tools don't fix it either because they can't trace a claim back to raw evidence.

## What Cortex does

|                              |                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| 🔌 **Ingests**               | GitHub repos (PRs and issues), Slack channels, and uploaded PDF/Word/text PRDs. Jira is a stretch goal. |
| 🕸️ **Builds a graph**        | Normalizes everything into typed nodes (requirements, decisions, evidence) joined by relationships.     |
| 🔗 **Connection Agent**      | Discovers relationships between artifacts and proposes them for human review.                           |
| ✂️ **Pruning Agent**         | Flags stale, weak, or contradictory information. It never deletes anything.                             |
| 💬 **Graph-Aware Assistant** | Answers natural-language questions about project history, with citations to source evidence.            |
| 🔍 **Explorer UI**           | Visual graph with filtering, search, zoom/pan, and one-click jumps to the original Slack message or PR. |

> **Status:** GitHub ingestion, the Explorer, authentication, workspace roles,
> and the assistant UI/API contract are built. The assistant currently uses a
> deterministic placeholder provider; graph retrieval and a hosted model remain
> planned. Slack, document uploads, and both agents are also planned.

## How it works

<p align="center">
  <img src="docs/images/architecture.png" alt="Cortex system architecture" width="760">
</p>

Cortex is a client-server system with a modular, service-oriented backend. The browser talks only to the API/Auth service over HTTPS/REST. The Ingestion service, the two agents, and the Assistant all read and write through one shared knowledge graph. Raw content lives in a separate evidence store and is referenced from the graph rather than copied into it.

### The data lifecycle

```mermaid
flowchart LR
    A[GitHub / Slack / PRD uploads] --> B[Ingestion Service<br/>normalize to artifacts]
    B --> C[(Knowledge Graph)]
    B --> E[(Evidence Store<br/>raw content)]
    C --> D[Connection Agent<br/>propose edges]
    D --> C
    C --> F[Pruning Agent<br/>flag issues]
    F --> G[Flagged Issues<br/>dashboard]
    C --> H[Explorer UI]
    C --> I[Graph-Aware Assistant]
    G -->|human review| C

    classDef src fill:#7ED321,stroke:#2c2c2c,color:#000
    classDef svc fill:#F5A623,stroke:#2c2c2c,color:#000
    classDef agent fill:#9B59B6,stroke:#2c2c2c,color:#fff
    classDef store fill:#E8544A,stroke:#2c2c2c,color:#fff
    classDef ui fill:#4A90D9,stroke:#2c2c2c,color:#fff
    class A src
    class B,I svc
    class D,F agent
    class C,E store
    class G,H ui
```

1. **Ingest.** A webhook, sync, or upload brings in a raw artifact. The Ingestion service normalizes it into a common format using a shared adapter interface, so new sources can be added without redesigning the pipeline.
2. **Link to evidence.** The artifact becomes a graph node with a pointer to the original content. Nothing enters the graph without provenance.
3. **Connect.** The Connection Agent searches for related nodes and proposes relationships as _pending_ edges.
4. **Prune.** On a schedule, the Pruning Agent sweeps the graph for stale or contradictory paths and raises flags.
5. **Review.** Humans approve or remove proposed edges, and resolve or dismiss flags.
6. **Ask.** Anyone can query the graph through the UI or the chat assistant.

## Core concepts

### Evidence-linked provenance

This is the rule everything else follows. **Every node and every edge resolves to raw evidence.** Open any node and you can jump straight to the Slack message, PR, or document section behind it.

### Node types

| Type                    | What it represents                                                          |
| ----------------------- | --------------------------------------------------------------------------- |
| `Requirement`           | A functional or non-functional requirement from a PRD, issue, or discussion |
| `Decision`              | A recorded team decision (a technology or design choice)                    |
| `Evidence`              | A pointer to raw source content backing a node or edge                      |
| `PullRequest` / `Issue` | Ingested from a connected GitHub repository                                 |
| `SlackMessage`          | Ingested from a connected Slack channel                                     |
| `Document`              | A section of an uploaded PDF or Word file                                   |
| `Flag`                  | A Pruning Agent finding attached to a node or edge                          |

Today the graph holds `Repository`, `Author`, `PullRequest`, and `Issue` nodes, each scoped to a workspace. The other types are planned.

### Relationship types

| Relationship   | Meaning                                              |
| -------------- | ---------------------------------------------------- |
| `SUPPORTS`     | An evidence node supports another node               |
| `REFERENCES`   | One artifact mentions or links to another            |
| `DEPENDS_ON`   | A requirement or decision depends on another         |
| `CONTRADICTS`  | Two nodes hold conflicting information               |
| `DERIVED_FROM` | A node was generated from a specific source artifact |
| `FLAGGED_BY`   | Links a flag to the node or edge it concerns         |

## The two agents

### Connection Agent: discover relationships

Runs shortly after each new artifact is ingested. It queries for related nodes and proposes edges, each with a confidence score and supporting evidence. Proposals are **pending** until a user approves, removes, or leaves them. You can also draw relationships manually when the agent misses one.

```mermaid
sequenceDiagram
    participant GH as GitHub
    participant ING as Ingestion Service
    participant DB as Knowledge Graph
    participant CA as Connection Agent

    GH->>ING: PR / issue event (sync today, webhook planned)
    ING->>ING: Normalize into candidate artifact
    ING->>DB: Write node + evidence link
    DB-->>ING: Ack (node ID)
    ING->>CA: New artifact ingested
    CA->>DB: Query related nodes
    DB-->>CA: Candidate matches
    CA->>DB: Propose relationship (pending review)
    Note over ING,DB: If ingestion fails, the source is marked with an<br/>error and previously ingested data is untouched.
```

### Pruning Agent: flag, never delete

Runs on a periodic sweep over the whole graph. When it finds something stale, weak, or contradictory, it creates a **Flag** and leaves the original node fully visible with a warning icon. Historical context is preserved while a human decides what to trust.

```mermaid
sequenceDiagram
    participant PA as Pruning Agent
    participant DB as Knowledge Graph
    participant UI as Web Client
    actor U as User

    PA->>DB: Scan for stale / contradictory paths
    DB-->>PA: Candidate nodes + evidence
    PA->>DB: Create flag (node stays visible)
    DB-->>UI: Flag appears on dashboard
    UI->>U: Display flagged issue
    U->>UI: Inspect evidence, resolve or dismiss
    UI->>DB: Update flag status
```

## The Graph-Aware Assistant

The assistant uses **retrieval-augmented generation over your own graph**. It doesn't answer from the LLM's general knowledge. It first retrieves the relevant subgraph and evidence, then prompts the model with that context, and returns the answer with numbered citations back to source artifacts.

```mermaid
sequenceDiagram
    actor U as User
    participant UI as Web Client
    participant AS as Assistant Service
    participant DB as Knowledge Graph
    participant LLM as LLM API

    U->>UI: "Why did we move away from Firebase?"
    UI->>AS: Query + workspace ID
    AS->>DB: Retrieve relevant nodes, edges, evidence
    DB-->>AS: Subgraph context
    AS->>LLM: Prompt with grounded context
    LLM-->>AS: Generated answer
    AS-->>UI: Answer + citations
    UI-->>U: Answer with clickable sources
```

Every claim in an answer can be clicked through to the original message, PR, or document, so you never have to take it on faith.


## Tech stack

What the repository uses today. Items marked _planned_ are in the design but not built yet.

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 | One app for routing, layout, and pages; `/api/*` is proxied to FastAPI |
| Graph rendering | Canvas-based explorer with a force-directed layout | SVG lags beyond a few dozen nodes and edges |
| Backend | Python 3.13 or lower, FastAPI, Pydantic v2, Uvicorn | Typed request/response validation |
| Relational database | PostgreSQL 16 via SQLAlchemy 2 and Alembic (psycopg 3) | Users, sessions, workspaces, memberships, roles, GitHub credentials, data sources |
| Graph database | Neo4j 5 (official `neo4j` driver) | Relationship traversal is the core operation; nodes are scoped by `workspace_id` |
| Auth | GitHub OAuth plus email/password; HttpOnly session cookies | Passwords hashed with Argon2; GitHub tokens encrypted at rest (Fernet) and never returned by the API |
| Authorization | Per-workspace roles (OWNER, EDITOR, VIEWER, plus custom roles) resolved to permissions on every request | Role changes and removals apply immediately |
| Integrations | GitHub REST (paginated, rate-limit aware) behind a source-adapter pattern | New sources plug in without changing the graph layer; Slack and file upload are _planned_ |
| Testing | pytest (backend), Vitest and Testing Library (frontend) | Backend unit tests need no Docker or network |
| Local infrastructure | Docker Compose (Postgres, Neo4j) | Named volumes keep data between restarts |
| Evidence storage | Object store (_planned_) | Keeps large raw content out of the graph |
| Agents and assistant | Hosted LLM API with strict Pydantic schemas on its output (_planned_) | Focus effort on graph quality and retrieval |

## Getting started

### Prerequisites

- Node.js 20.9 or newer and npm
- Python 3.13 or lower (3.14 is not supported by some pinned packages)
- Docker Desktop
- A [GitHub OAuth app](https://github.com/settings/developers) whose callback URL is `http://localhost:3000/auth/github/callback`
- Rust toolchain, only if `pip` has to build `watchfiles` from source

Slack and LLM credentials are not needed yet; those features are not built.

### 1. Configure the environment

```bash
cp .env.example .env
```

Edit `.env`. Credentials and tokens must **never** be committed or exposed in the UI.

| Variable | Purpose |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | Postgres container |
| `DATABASE_URL` | `postgresql+psycopg://user:password@localhost:5432/db`; keep the port in sync |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Neo4j connection and container login |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OAUTH_REDIRECT_URI` | GitHub sign-in |
| `TOKEN_ENCRYPTION_KEY` | Required. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GITHUB_TOKEN` | Optional; raises the GitHub API limit from 60 to 5,000 requests per hour |
| `ASSISTANT_RATE_LIMIT_PER_MINUTE`, `ASSISTANT_TIMEOUT_SECONDS` | Bounds assistant request frequency and provider latency |
| `SECURE_COOKIES` | Set to `true` outside local HTTP development |

If you change the Postgres or Neo4j credentials after the first start, Docker keeps the old ones in its volumes. Run `docker compose down -v` to reset them.

### 2. Start the databases

```bash
docker compose up -d postgres neo4j
```

### 3. Start the backend

```bash
cd backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.init_graph_schema      # Neo4j constraints
python -m scripts.init_postgres_schema   # Alembic migrations
python -m scripts.dev_workspace trial    # optional: seed two users and four workspaces
uvicorn app.main:app --reload
```

The API runs on `http://127.0.0.1:8000`, with interactive docs at `/docs`. The seeded users sign in with `trial-owner@example.com` and `local-development-password`. More detail is in [backend/README.md](backend/README.md).

### 4. Start the frontend

From the repository root, in a second terminal:

```bash
npm --prefix apps/web install
npm run dev
```

Open `http://localhost:3000` and sign in.

### Keep the local app running

Run the development watchdog from the repository root:

```bash
npm run dev:watch
```

It monitors the frontend and backend health endpoints, restarts failed services,
and writes logs to `.cortex-dev/`. Press `Ctrl+C` to stop services started by the
watchdog. Both services bind to `127.0.0.1` by default; set
`CORTEX_BIND_HOST=0.0.0.0` only when access from another device is intentional.
Use `npm run dev:watch -- --check` for a one-time health check.

An isolated worktree can reuse another checkout's `.env` and Python environment:

```bash
CORTEX_RUNTIME_ROOT=/path/to/configured/cortex npm run dev:watch
```

### Tests

```bash
cd backend && pytest        # backend
npm test                    # frontend, from the repository root
npm run lint
```

## Project structure

```
apps/web/          Next.js frontend (routes in src/app, components in src/components)
backend/app/       FastAPI backend
  api/             Routers: auth, workspaces, roles, graph, ingest, health
  services/        Business rules: workspaces, roles, data sources, GitHub credentials
  models/          SQLAlchemy models
  github/          GitHub client, OAuth, payload models, and Cypher mapper
  graph/           Cypher read queries for the explorer
  db/              Postgres and Neo4j connections and graph constraints
backend/alembic/   Postgres migrations
backend/scripts/   Schema setup, seed data, key rotation
backend/tests/     pytest suite
docker-compose.yml Postgres and Neo4j for local development
docs/images/       Architecture diagram
```

## Roadmap

| Area | Status |
| --- | --- |
| GitHub and email sign-in, sessions, encrypted tokens | Done |
| Workspaces, memberships, roles and custom permissions | Done (backend; role management UI pending) |
| GitHub ingestion of pull requests and issues | Done |
| Graph Explorer with zoom, pan, and node and edge details | Done |
| Source sync status | Done |
| Invite and remove members, delete a workspace | In progress |
| Slack and document ingestion, evidence store | Planned |
| Connection Agent, Pruning Agent, flagged issues dashboard | Planned |
| Graph-Aware Assistant UI and secured placeholder API | Done; graph retrieval and hosted model planned |
| Jira integration | Stretch |

## Design principles

- **Provenance first.** Nothing enters the graph without a link to the raw evidence behind it.
- **Flag, never delete.** Agents raise warnings; humans decide what to trust.
- **Humans review agent output.** Proposed edges stay pending until someone approves them.
- **Adapters, not special cases.** Every source is translated into one common artifact format before it reaches the graph.
- **Validate everything an LLM returns.** Model output must pass strict schemas before it is stored.
- **Secrets stay server-side.** Tokens are encrypted at rest and never returned by the API.

## Team

| Name          | Email               |
| ------------- | ------------------- |
| Parth Ranade  | ranadep@purdue.edu  |
| Ashwath Singh | sing1184@purdue.edu |
| Aryan Jumani  | ajumani@purdue.edu  |
| Kuanyu Chen   | chen4396@purdue.edu |
