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
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.db.neo4j_driver import get_driver
from app.graph.queries import (
    DEFAULT_EDGE_LIMIT,
    DEFAULT_NODE_LIMIT,
    GRAPH_LABELS,
    coerce_node_id,
    fetch_edge_details,
    fetch_graph,
    fetch_node_details,
    fetch_source_summaries,
    mutate_graph_edge,
)
from app.models import SyncStatus
from app.permissions import Permission
from app.services.chat_credentials import list_chat_connections
from app.services.data_sources import build_source_inventory, list_synced_sources

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
    """One connected source: sync state from Postgres, counts from Neo4j.

    ``repo`` is the source's ``external_ref`` -- ``owner/name`` for GitHub, the
    filename for an uploaded document, the Slack team id or Discord guild id for
    a chat source. The field name predates all three and the Sources page builds
    on it, so it stays. Which counts are meaningful depends on ``kind``: every
    other count is zero.
    """

    repo: str
    kind: str
    status: SyncStatus
    pull_requests: int
    issues: int
    total_items: int
    sections: int = 0
    channels: int = 0
    messages: int = 0
    #: What to call the source on screen when its reference is not its name:
    #: the filename for an upload, the team or server name for a chat source.
    display_name: str | None = None
    last_attempted_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_error: str | None = None
    #: T-12.1: the failure category behind ``last_error``, or null when the
    #: source is not failing. ``app.services.source_failures.FailureCategory``.
    last_error_code: str | None = None
    last_synced_by: uuid.UUID | None = None
    last_synced_by_name: str | None = None


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


class GraphEdgeMutation(BaseModel):
    source_key: str
    target_key: str
    edge_type: str = Field(default="MANUAL_RELATIONSHIP", min_length=1, max_length=100)
    relationship_type: str = Field(default="RELATED_TO", min_length=1, max_length=100)
    rationale: str = Field(default="", max_length=2000)


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
    """T-10.1: the workspace's sources, with sync status and timestamps.

    ``data_sources`` is the authoritative list -- a repository whose ingestion
    failed has no graph nodes and must still appear, with zero items, so the UI
    can flag it. Neo4j supplies the counts.

    A Neo4j outage is still a 503 rather than a degraded list: the counts would
    read as zero, which is exactly how a failed ingestion looks, and quietly
    showing that is worse than an error the page already offers a retry for.

    Chat sources carry a display name (US-08 AC3): their ``external_ref`` is a
    Slack team id or Discord guild id, and the graph does not hold the team's
    name, so it is read from the connection that was authorised.
    """
    load_workspace_for_user(session, user, workspace_id)

    try:
        summaries = fetch_source_summaries(driver, workspace_id)
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    display_names = {
        row.external_ref: row.display_name
        for row in list_chat_connections(session, workspace_id).values()
    }

    return [
        SourceSummary(
            repo=item.repo,
            kind=item.kind,
            status=item.status,
            pull_requests=item.pull_requests,
            issues=item.issues,
            total_items=item.total_items,
            sections=item.sections,
            channels=item.channels,
            messages=item.messages,
            display_name=item.display_name,
            last_attempted_at=item.last_attempted_at,
            last_synced_at=item.last_synced_at,
            last_error=item.last_error,
            last_error_code=item.last_error_code,
            last_synced_by=item.last_synced_by,
            last_synced_by_name=item.last_synced_by_name,
        )
        for item in build_source_inventory(
            list_synced_sources(session, workspace_id), summaries, display_names
        )
    ]


@router.get("/{workspace_id}/graph", response_model=GraphResponse)
def read_workspace_graph(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    node_limit: int = Query(DEFAULT_NODE_LIMIT, ge=1, le=10_000),
    edge_limit: int = Query(DEFAULT_EDGE_LIMIT, ge=1, le=30_000),
    types: list[str] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    driver: Driver = Depends(get_neo4j),
) -> GraphResponse:
    load_workspace_for_user(session, user, workspace_id)

    selected_types = [node_type for node_type in (types or []) if node_type]
    if types is not None and any(node_type not in GRAPH_LABELS for node_type in selected_types):
        raise HTTPException(status_code=422, detail="Invalid graph node type")

    try:
        payload = fetch_graph(
            driver,
            workspace_id,
            node_limit=node_limit,
            edge_limit=edge_limit,
            node_types=selected_types if types is not None else None,
            search_query=q,
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
    # ``:path`` because an uploaded-document or chat node id contains slashes
    # (``upload/4f1c…/3``, ``slack/C0ABC/1730000000.123456``); without it the id
    # would be split across path segments and never match a route.
    "/{workspace_id}/graph/nodes/{node_type}/{node_id:path}",
    response_model=GraphNodeDetails,
)
def read_graph_node_details(
    workspace_id: uuid.UUID,
    node_type: Literal[
        "Author",
        "PullRequest",
        "Issue",
        "Document",
        "DocumentSection",
        "Channel",
        "Message",
    ],
    node_id: str,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> GraphNodeDetails:
    load_workspace_for_user(session, user, workspace_id)
    if not node_id:
        raise HTTPException(status_code=404, detail="Graph node not found")
    try:
        payload = fetch_node_details(
            driver, workspace_id, node_type, coerce_node_id(node_id)
        )
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


@router.delete("/{workspace_id}/graph/edges")
def delete_graph_edge(
    workspace_id: uuid.UUID,
    body: GraphEdgeMutation,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> dict[str, bool]:
    load_workspace_for_user(session, user, workspace_id, permission=Permission.SOURCES_WRITE)
    try:
        deleted = mutate_graph_edge(driver, workspace_id, body.source_key, body.target_key,
                                    body.edge_type, delete=True)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid graph node key")
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    if not deleted:
        raise HTTPException(status_code=404, detail="Graph edge not found")
    return {"deleted": True}


@router.post("/{workspace_id}/graph/edges", response_model=GraphEdge)
def create_graph_edge(
    workspace_id: uuid.UUID,
    body: GraphEdgeMutation,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> GraphEdge:
    load_workspace_for_user(session, user, workspace_id, permission=Permission.SOURCES_WRITE)
    try:
        created = mutate_graph_edge(driver, workspace_id, body.source_key, body.target_key,
                                    "MANUAL_RELATIONSHIP", delete=False,
                                    relationship_type=body.relationship_type,
                                    rationale=body.rationale, created_by=str(user.id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid graph node key")
    except (Neo4jError, DriverError):
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    if not created:
        raise HTTPException(status_code=409, detail="Relationship already exists or node not found")
    return GraphEdge(source=body.source_key, target=body.target_key, type="MANUAL_RELATIONSHIP")
