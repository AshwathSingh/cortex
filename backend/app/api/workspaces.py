"""T-41.3: workspaces the calling user is authorised to open.
    GET /api/workspaces        every workspace the caller can access
    GET /api/workspaces/{id}   does the user have some access on this workspace
    POST /api/workspaces       create a workspace owned by the caller (US-2)
    DELETE /api/workspaces/{id} delete it and everything in it (US-05)

Ownership and access roles both live in ``workspace_memberships``, so every
authorization decision reads the same source of truth.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from neo4j import Driver
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.db.neo4j_driver import get_driver
from app.models import WORKSPACE_ACTIVE, Role, Workspace, WorkspaceMembership
from app.permissions import (
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    membership_permissions,
    permission_values,
    role_label,
)
from app.services.roles import RoleError
from app.services.workspaces import (
    WorkspaceNameTaken,
    create_workspace,
    delete_workspace,
    update_workspace,
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


class WorkspaceUpdate(WorkspaceCreate):
    """The editable workspace profile fields."""


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


@router.patch("/{workspace_id}", response_model=WorkspaceSummary)
def update_workspace_profile(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
    user: CurrentUser,
    session: DbSession,
) -> WorkspaceSummary:
    workspace, membership = load_workspace_for_user(session, user, workspace_id)
    if membership.role is not Role.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners can edit workspace details",
        )

    try:
        update_workspace(
            session,
            workspace=workspace,
            name=payload.name,
            description=payload.description,
        )
        session.commit()
    except WorkspaceNameTaken:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a workspace named '{payload.name}'",
        )

    return _summarise(workspace, membership)


class WorkspaceDelete(BaseModel):
    #: Typed by the user in the confirmation modal. Optional here only so that a
    #: missing value is a clear 400 from the handler rather than a generic 422.
    confirm_name: str | None = None


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace_endpoint(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    body: WorkspaceDelete | None = Body(default=None),
    driver: Driver = Depends(get_neo4j),
) -> Response:
    """Delete the workspace and everything in it: graph nodes and edges, members,
    invites, custom roles and data sources.

    Only an owner (``workspace.delete``), and the body must carry
    ``{"confirm_name": "<exact workspace name>"}`` (case-sensitive, no trimming) or
    this is a 400. Both checks run before anything is marked or deleted, in that
    order: a caller who isn't allowed gets 403 whatever they typed, so the response
    never reveals whether a guessed name was right. If a store fails part-way the workspace
    stays hidden in a ``deleting`` state and this endpoint returns 500; calling it
    again resumes the cleanup. Authorisation runs first, so a refused caller
    touches no data.
    """
    workspace, actor = load_workspace_for_user(
        session,
        user,
        workspace_id,
        permission=Permission.WORKSPACE_DELETE,
        include_deleting=True,  # so a half-finished delete can be retried
    )
    confirm_name = body.confirm_name if body else None
    if confirm_name is None or confirm_name != workspace.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="To delete this workspace, send its exact name as 'confirm_name'. "
            "Nothing was deleted.",
        )
    try:
        delete_workspace(session, driver, workspace_id, actor)
    except RoleError as e:  # lost the right to delete between the check and the lock
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception:
        # Already logged with detail by the service; keep internals out of the body.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The workspace could not be fully deleted. It is hidden and "
            "no longer usable; try deleting it again to finish.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
