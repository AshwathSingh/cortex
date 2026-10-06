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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.db.neo4j_driver import get_driver
from app.graph.queries import (
    DEFAULT_EDGE_LIMIT,
    DEFAULT_NODE_LIMIT,
    fetch_edge_details,
    fetch_graph,
    fetch_node_details,
    fetch_source_summaries,
)

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


class SourceSummary(BaseModel):
    repo: str
    pull_requests: int
    issues: int
    total_items: int


class GraphOrigin(BaseModel):
    key: str
    type: str
    title: str
    url: str
    relationship: str | None = None
    direction: Literal["incoming", "outgoing"] | None = None


class GraphNodeDetails(BaseModel):
    key: str
    id: int | str | None = None
    type: str
    title: str
    content: str | None = None
    attributes: dict[str, Any]
    origins: list[GraphOrigin]


class GraphEndpointDetails(GraphNodeDetails):
    pass


class GraphEdgeDetails(BaseModel):
    key: str
    type: str
    title: str
    content: str
    source: GraphEndpointDetails
    target: GraphEndpointDetails
    attributes: dict[str, Any]
    origins: list[GraphOrigin]


def get_neo4j() -> Driver:
    """Injectable so tests can supply a fake driver (same shape as app.api.ingest)."""
    return get_driver()


@router.get("/{workspace_id}/sources", response_model=list[SourceSummary])
def read_workspace_sources(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> list[SourceSummary]:
    load_workspace_for_user(session, user, workspace_id)

    try:
        sources = fetch_source_summaries(driver, workspace_id)
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    return [
        SourceSummary(
            repo=source.repo,
            pull_requests=source.pull_requests,
            issues=source.issues,
            total_items=source.total_items,
        )
        for source in sources
    ]


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


@router.get(
    "/{workspace_id}/graph/nodes/{node_type}/{node_id}",
    response_model=GraphNodeDetails,
)
def read_graph_node_details(
    workspace_id: uuid.UUID,
    node_type: Literal["Author", "PullRequest", "Issue"],
    node_id: int,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> GraphNodeDetails:
    load_workspace_for_user(session, user, workspace_id)
    try:
        payload = fetch_node_details(driver, workspace_id, node_type, node_id)
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    if payload is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return GraphNodeDetails(**payload)


@router.get("/{workspace_id}/graph/edges", response_model=GraphEdgeDetails)
def read_graph_edge_details(
    workspace_id: uuid.UUID,
    source_key: str,
    target_key: str,
    edge_type: str,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> GraphEdgeDetails:
    load_workspace_for_user(session, user, workspace_id)
    try:
        payload = fetch_edge_details(
            driver, workspace_id, source_key, target_key, edge_type
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid graph node key")
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    if payload is None:
        raise HTTPException(status_code=404, detail="Graph edge not found")
    return GraphEdgeDetails(**payload)
