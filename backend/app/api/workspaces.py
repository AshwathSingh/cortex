"""T-41.3: workspaces the calling user is authorised to open.
    GET /api/workspaces        every workspace the caller can access
    GET /api/workspaces/{id}   does the user have some access on this workspace

A VIEWER is authorised to open a workspace they do not own, so both endpoints read
``workspace_memberships`` rather than ``workspaces.owner_id``.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Role, Workspace, WorkspaceMembership

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceSummary(BaseModel):
    """One entry in the Workspace Selector."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: Role  # the caller's role, not the workspace's
    created_at: datetime


def _summarise(workspace: Workspace, role: Role) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        role=role,
        created_at=workspace.created_at,
    )


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(user: CurrentUser, session: DbSession) -> list[WorkspaceSummary]:
    """Every workspace the caller holds any role on, ordered by name.
    Returns empty if user has access to no workspaces.
    """
    rows = session.execute(
        select(Workspace, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(Workspace.name)
    ).all()

    return [_summarise(workspace, role) for workspace, role in rows]


@router.get("/{workspace_id}", response_model=WorkspaceSummary)
def get_workspace(
    workspace_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> WorkspaceSummary:
    """One workspace, or 403 if the caller holds no role on it.

    Note: a non-existent workspace and a workspace the caller doesn't have access
        to return the same 403 (to prevent anyone knowing which workspaces exist and
    which don't)
    """
    row = session.execute(
        select(Workspace, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    ).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this workspace",
        )

    workspace, role = row
    return _summarise(workspace, role)
