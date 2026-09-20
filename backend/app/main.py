from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import ingest
from app.db.neo4j_driver import close_driver


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_driver()


app = FastAPI(title="Cortex", lifespan=lifespan)
app.include_router(ingest.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
