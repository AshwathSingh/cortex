from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, graph, health, ingest, workspaces
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
# After workspaces.router: both own /api/workspaces, and the more specific
# /{workspace_id}/graph must not be shadowed by /{workspace_id}.
app.include_router(graph.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
