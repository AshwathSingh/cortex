"""US-23: Connection Agent review queue, analysis status and retry.

    GET  /api/workspaces/{id}/connections/summary               any member
    GET  /api/workspaces/{id}/connections/suggestions           any member (read-only list)
    POST /api/workspaces/{id}/connections/suggestions/{edge}/approve|reject   editors
    POST /api/workspaces/{id}/connections/retry                 editors

Approve/reject need ``sources.write`` (the same editor permission as drawing or
removing a relationship), enforced here on the server; viewers get 403.
"""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel

from app.agent import events
from app.agent.store import Neo4jStore
from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.config import settings
from app.db.neo4j_driver import get_driver
from app.graph.mutations import review_agent_edge
from app.permissions import Permission

router = APIRouter(prefix="/api/workspaces", tags=["connections"])


class Endpoint(BaseModel):
    key: str
    type: str
    title: str
    url: str | None = None


class Suggestion(BaseModel):
    id: str
    relationship_type: str
    confidence: float
    evidence: str | None = None
    created_at: str | None = None
    source: Endpoint
    target: Endpoint


class ConnectionSummary(BaseModel):
    enabled: bool
    pending_review: int
    #: artifacts by analysis status: pending | running | done | failed | unanalysed
    analysis: dict[str, int]


def get_neo4j() -> Driver:
    return get_driver()


def _graph_down() -> HTTPException:
    return HTTPException(status_code=503, detail="Graph database unavailable")


@router.get("/{workspace_id}/connections/summary", response_model=ConnectionSummary)
def read_summary(workspace_id: uuid.UUID, user: CurrentUser, session: DbSession,
                 driver: Driver = Depends(get_neo4j)) -> ConnectionSummary:
    load_workspace_for_user(session, user, workspace_id)
    try:
        counts = Neo4jStore(driver).analysis_summary(str(workspace_id))
    except (Neo4jError, DriverError):
        raise _graph_down()
    pending = counts.pop("pending_review", 0)
    return ConnectionSummary(enabled=settings.connection_agent_enabled,
                             pending_review=pending, analysis=counts)


@router.get("/{workspace_id}/connections/suggestions", response_model=list[Suggestion])
def read_suggestions(workspace_id: uuid.UUID, user: CurrentUser, session: DbSession,
                     driver: Driver = Depends(get_neo4j)) -> list[dict[str, Any]]:
    load_workspace_for_user(session, user, workspace_id)
    try:
        return Neo4jStore(driver).list_suggestions(str(workspace_id))
    except (Neo4jError, DriverError):
        raise _graph_down()


def _review(workspace_id: uuid.UUID, edge_id: str, user, session, driver, *, approve: bool):
    load_workspace_for_user(session, user, workspace_id, permission=Permission.SOURCES_WRITE)
    try:
        done = review_agent_edge(driver, str(workspace_id), edge_id=edge_id,
                                 approve=approve, user_id=str(user.id))
    except (Neo4jError, DriverError):
        raise _graph_down()
    if not done:
        raise HTTPException(status_code=404, detail="Suggestion not found or already reviewed")
    return {"status": "active" if approve else "rejected"}


@router.post("/{workspace_id}/connections/suggestions/{edge_id}/approve")
def approve_suggestion(workspace_id: uuid.UUID, edge_id: str, user: CurrentUser,
                       session: DbSession, driver: Driver = Depends(get_neo4j)):
    return _review(workspace_id, edge_id, user, session, driver, approve=True)


@router.post("/{workspace_id}/connections/suggestions/{edge_id}/reject")
def reject_suggestion(workspace_id: uuid.UUID, edge_id: str, user: CurrentUser,
                      session: DbSession, driver: Driver = Depends(get_neo4j)):
    return _review(workspace_id, edge_id, user, session, driver, approve=False)


@router.post("/{workspace_id}/connections/retry", status_code=202)
def retry_analysis(workspace_id: uuid.UUID, background: BackgroundTasks, user: CurrentUser,
                   session: DbSession) -> dict[str, str]:
    """Re-run analysis for artifacts that failed or changed. Artifacts that
    failed never recorded a content hash, so the normal sweep picks them up."""
    load_workspace_for_user(session, user, workspace_id, permission=Permission.SOURCES_WRITE)
    if not settings.connection_agent_enabled:
        raise HTTPException(status_code=503, detail="Connection agent is not configured")
    background.add_task(events.emit_artifact_ingested, workspace_id)
    return {"status": "queued"}
