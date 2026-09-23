from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import ingest, workspaces
from app.db.neo4j_driver import close_driver
from app.db.postgres import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_driver()
    dispose_engine()


app = FastAPI(title="Cortex", lifespan=lifespan)
app.include_router(ingest.router)
app.include_router(workspaces.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
