from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    assistant,
    auth,
    flags,
    graph,
    graph_comments,
    health,
    ingest,
    invites,
    members,
    roles,
    source_failures,
    sources,
    uploads,
    workspaces,
)
from app.db.neo4j_driver import close_driver
from app.db.postgres import dispose_engine
from app.security import validate_encryption_keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_encryption_keys()
    yield
    close_driver()
    dispose_engine()


app = FastAPI(title="Cortex", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(workspaces.router)
app.include_router(roles.catalogue_router)
app.include_router(roles.router)
app.include_router(assistant.router)
app.include_router(invites.router)
app.include_router(invites.accept_router)
app.include_router(members.router)
# After workspaces.router: both own /api/workspaces, and the more specific
# /{workspace_id}/graph and /{workspace_id}/connections must not be shadowed by
# /{workspace_id}.
app.include_router(graph.router)
app.include_router(flags.router)
app.include_router(sources.router)
app.include_router(uploads.router)
# Before graph.router would also work -- the paths are literal and do not
# overlap -- but keeping every /api/workspaces router after workspaces.router
# is the rule that stops /{workspace_id} shadowing anything.
app.include_router(graph_comments.router)
app.include_router(source_failures.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
