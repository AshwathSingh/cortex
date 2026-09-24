"""T-41.3: workspaces the calling user is authorised to open.
    GET /api/workspaces        every workspace the caller can access
    GET /api/workspaces/{id}   does the user have some access on this workspace
    POST /api/workspaces       create a workspace owned by the caller (US-2)

Ownership and access roles both live in ``workspace_memberships``, so every
authorization decision reads the same source of truth.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Role, Workspace, WorkspaceMembership
from app.services.workspaces import WorkspaceNameTaken, create_workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceSummary(BaseModel):
    """One entry in the Workspace Selector."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    role: Role  # the caller's role, not the workspace's
    created_at: datetime


class WorkspaceCreate(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
        | None
    ) = None

    @field_validator("description")
    @classmethod
    def _blank_description_is_none(cls, v: str | None) -> str | None:
        return v or None


def _summarise(workspace: Workspace, role: Role) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
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


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
def create_new_workspace(
    payload: WorkspaceCreate, user: CurrentUser, session: DbSession
) -> WorkspaceSummary:
    """Create a workspace with the caller as its OWNER.

    409 if the caller already owns a workspace with this name (case-insensitive).
    """
    try:
        workspace = create_workspace(
            session, name=payload.name, owner=user, description=payload.description
        )
        session.commit()
    except WorkspaceNameTaken:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a workspace named '{payload.name}'",
        )

    # created_at is a server default, so read it back after the insert.
    session.refresh(workspace)
    return _summarise(workspace, Role.OWNER)


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
