"""T-41.3: workspaces the calling user is authorised to open.
    GET /api/workspaces        every workspace the caller can access
    GET /api/workspaces/{id}   does the user have some access on this workspace
    POST /api/workspaces       create a workspace owned by the caller (US-2)
    DELETE /api/workspaces/{id} delete it and everything in it (US-05)

Ownership and access roles both live in ``workspace_memberships``, so every
authorization decision reads the same source of truth.
"""

import uuid
from datetime import datetime
from typing import Annotated

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from neo4j import Driver
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.models import WORKSPACE_ACTIVE, Role, Workspace, WorkspaceMembership
from app.permissions import (
    SYSTEM_ROLE_PERMISSIONS,
    membership_permissions,
    permission_values,
    role_label,
)
from app.db.neo4j_driver import get_driver
from app.permissions import Permission
from app.services.workspaces import (
    WorkspaceNameTaken,
    create_workspace,
    delete_workspace,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def get_neo4j() -> Driver:
    """Injectable so tests can supply a fake driver (same shape as app.api.ingest)."""
    return get_driver()


class WorkspaceSummary(BaseModel):
    """One entry in the Workspace Selector."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    role: str  # the caller's role name, not the workspace's
    permissions: list[str]  # what that role lets the caller do
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


def _summarise(workspace: Workspace, membership: WorkspaceMembership) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        role=role_label(membership),
        permissions=permission_values(membership_permissions(membership)),
        created_at=workspace.created_at,
    )


@router.get("", response_model=list[WorkspaceSummary])
def list_workspaces(user: CurrentUser, session: DbSession) -> list[WorkspaceSummary]:
    """Every workspace the caller holds any role on, ordered by name.
    Returns empty if user has access to no workspaces.
    """
    rows = session.execute(
        select(Workspace, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == user.id,
            Workspace.status == WORKSPACE_ACTIVE,  # hide ones being deleted
        )
        .order_by(Workspace.name)
    ).all()

    return [_summarise(workspace, membership) for workspace, membership in rows]


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
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        role=Role.OWNER.value,
        permissions=permission_values(SYSTEM_ROLE_PERMISSIONS[Role.OWNER]),
        created_at=workspace.created_at,
    )


@router.get("/{workspace_id}", response_model=WorkspaceSummary)
def get_workspace(
    workspace_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> WorkspaceSummary:
    """One workspace, or 403 if the caller holds no role on it.

    Note: a non-existent workspace and a workspace the caller doesn't have access
        to return the same 403 (to prevent anyone knowing which workspaces exist and
    which don't)
    """
    workspace, membership = load_workspace_for_user(session, user, workspace_id)
    return _summarise(workspace, membership)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace_endpoint(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    driver: Driver = Depends(get_neo4j),
) -> Response:
    """Delete the workspace and everything in it: graph nodes and edges, members,
    invites, custom roles and data sources.

    Only an owner (``workspace.delete``). If a store fails part-way the workspace
    stays hidden in a ``deleting`` state and this endpoint returns 500; calling it
    again resumes the cleanup. Authorisation runs first, so a refused caller
    touches no data.
    """
    load_workspace_for_user(
        session,
        user,
        workspace_id,
        permission=Permission.WORKSPACE_DELETE,
        include_deleting=True,  # so a half-finished delete can be retried
    )
    try:
        delete_workspace(session, driver, workspace_id)
    except Exception:
        # Already logged with detail by the service; keep internals out of the body.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The workspace could not be fully deleted. It is hidden and "
            "no longer usable; try deleting it again to finish.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
