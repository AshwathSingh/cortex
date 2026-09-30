"""T-14.1: the Graph Explorer's bulk read.

    GET /api/workspaces/{workspace_id}/graph

Returns every node and edge in one workspace, for the canvas to lay out. Any
role may read -- a VIEWER is meant to see the graph; only writes need
OWNER/EDITOR. A caller with no role gets the same 403 as a workspace that does
not exist, matching `GET /api/workspaces/{id}`.

Authorisation runs before the graph read, so an unauthorised caller never reaches
Neo4j.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.db.neo4j_driver import get_driver
from app.graph.queries import DEFAULT_EDGE_LIMIT, DEFAULT_NODE_LIMIT, fetch_graph

router = APIRouter(prefix="/api/workspaces", tags=["graph"])


class GraphNode(BaseModel):
    key: str  # "PullRequest:42" -- a GitHub id alone is not unique across labels
    id: int | str | None = None
    type: str
    title: str
    url: str | None = None
    state: str | None = None
    repo: str | None = None
    number: int | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    workspace_id: uuid.UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


def get_neo4j() -> Driver:
    """Injectable so tests can supply a fake driver (same shape as app.api.ingest)."""
    return get_driver()


@router.get("/{workspace_id}/graph", response_model=GraphResponse)
def read_workspace_graph(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    node_limit: int = Query(DEFAULT_NODE_LIMIT, ge=1, le=10_000),
    edge_limit: int = Query(DEFAULT_EDGE_LIMIT, ge=1, le=30_000),
    driver: Driver = Depends(get_neo4j),
) -> GraphResponse:
    load_workspace_for_user(session, user, workspace_id)

    try:
        payload = fetch_graph(
            driver, workspace_id, node_limit=node_limit, edge_limit=edge_limit
        )
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    return GraphResponse(
        workspace_id=payload.workspace_id,
        nodes=[GraphNode(**node) for node in payload.nodes],
        edges=[GraphEdge(**edge) for edge in payload.edges],
        truncated=payload.truncated,
    )
