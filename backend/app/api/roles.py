"""US-21: custom roles and member role assignment.

    GET    /api/permissions                                  the permission catalogue
    GET    /api/workspaces/{id}/roles                        built-in + custom roles
    POST   /api/workspaces/{id}/roles                        create a custom role
    PATCH  /api/workspaces/{id}/roles/{role_id}              edit name/description/permissions
    DELETE /api/workspaces/{id}/roles/{role_id}              delete an unassigned custom role
    GET    /api/workspaces/{id}/members                      members and their roles
    PATCH  /api/workspaces/{id}/members/{user_id}/role       assign a role to a member

Reading needs membership only; creating, editing and deleting roles needs
``roles.manage``; assigning roles needs ``members.manage``. The guards that stop a
member handing out permissions they lack live in ``app.services.roles``.

Deviation from the sprint spec: a role is identified by ``role_id`` (custom) or
``role`` (built-in OWNER/EDITOR/VIEWER) because roles are now user-defined.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.models import Role, User, WorkspaceMembership, WorkspaceRole
from app.permissions import (
    GRANTABLE,
    PERMISSION_DESCRIPTIONS,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    membership_permissions,
    parse_permissions,
    permission_values,
    role_label,
)
from app.services import roles as role_service
from app.services.roles import RoleChoice, RoleError

catalogue_router = APIRouter(prefix="/api/permissions", tags=["roles"])
router = APIRouter(prefix="/api/workspaces", tags=["roles"])

RoleName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
RoleDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class PermissionInfo(BaseModel):
    key: str
    description: str
    grantable: bool  # False: only the built-in OWNER role carries it


class RoleOut(BaseModel):
    id: uuid.UUID | None  # None for built-in roles
    name: str
    description: str | None
    permissions: list[str]
    built_in: bool
    member_count: int


class RoleCreate(BaseModel):
    name: RoleName
    description: RoleDescription | None = None
    permissions: list[Permission] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v or None


class RoleUpdate(BaseModel):
    name: RoleName | None = None
    description: RoleDescription | None = None
    permissions: list[Permission] | None = None

    @field_validator("description")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v or None


class RoleAssignment(BaseModel):
    """Exactly one of ``role`` (built-in) or ``role_id`` (custom)."""

    role: Role | None = None
    role_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "RoleAssignment":
        if (self.role is None) == (self.role_id is None):
            raise ValueError("Provide exactly one of 'role' or 'role_id'")
        return self


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    name: str | None
    email: str | None
    role: str
    role_id: uuid.UUID | None
    permissions: list[str]
    created_at: datetime


def _raise(error: RoleError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def _custom_out(role: WorkspaceRole, member_count: int) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=permission_values(parse_permissions(role.permissions) & GRANTABLE),
        built_in=False,
        member_count=member_count,
    )


def _member_out(membership: WorkspaceMembership, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        name=user.display_name,
        email=user.email,
        role=role_label(membership),
        role_id=membership.custom_role_id,
        permissions=permission_values(membership_permissions(membership)),
        created_at=membership.invited_at,
    )


@catalogue_router.get("", response_model=list[PermissionInfo])
def list_permissions(user: CurrentUser) -> list[PermissionInfo]:
    """Every permission a role can hold, for building a role editor."""
    return [
        PermissionInfo(
            key=p.value, description=PERMISSION_DESCRIPTIONS[p], grantable=p in GRANTABLE
        )
        for p in Permission
    ]


@router.get("/{workspace_id}/roles", response_model=list[RoleOut])
def list_roles(
    workspace_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[RoleOut]:
    load_workspace_for_user(session, user, workspace_id)

    builtin_counts = dict(
        session.execute(
            select(WorkspaceMembership.role, func.count())
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role.is_not(None),
            )
            .group_by(WorkspaceMembership.role)
        ).all()
    )
    custom_counts = dict(
        session.execute(
            select(WorkspaceMembership.custom_role_id, func.count())
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.custom_role_id.is_not(None),
            )
            .group_by(WorkspaceMembership.custom_role_id)
        ).all()
    )

    result = [
        RoleOut(
            id=None,
            name=role.value,
            description=None,
            permissions=permission_values(SYSTEM_ROLE_PERMISSIONS[role]),
            built_in=True,
            member_count=builtin_counts.get(role, 0),
        )
        for role in Role
    ]
    custom = session.scalars(
        select(WorkspaceRole)
        .where(WorkspaceRole.workspace_id == workspace_id)
        .order_by(func.lower(WorkspaceRole.name))
    ).all()
    result += [_custom_out(r, custom_counts.get(r.id, 0)) for r in custom]
    return result


@router.post(
    "/{workspace_id}/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED
)
def create_custom_role(
    workspace_id: uuid.UUID, body: RoleCreate, user: CurrentUser, session: DbSession
) -> RoleOut:
    _, actor = load_workspace_for_user(
        session, user, workspace_id, permission=Permission.ROLES_MANAGE
    )
    try:
        role = role_service.create_role(
            session,
            workspace_id=workspace_id,
            actor=actor,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
        )
        session.commit()
    except RoleError as e:
        session.rollback()
        raise _raise(e)
    return _custom_out(role, 0)


@router.patch("/{workspace_id}/roles/{role_id}", response_model=RoleOut)
def update_custom_role(
    workspace_id: uuid.UUID,
    role_id: uuid.UUID,
    body: RoleUpdate,
    user: CurrentUser,
    session: DbSession,
) -> RoleOut:
    _, actor = load_workspace_for_user(
        session, user, workspace_id, permission=Permission.ROLES_MANAGE
    )
    try:
        role = role_service.get_custom_role(session, workspace_id, role_id)
        role_service.update_role(
            session,
            role=role,
            actor=actor,
            name=body.name,
            description=body.description,
            description_set="description" in body.model_fields_set,
            permissions=body.permissions,
        )
        session.commit()
    except RoleError as e:
        session.rollback()
        raise _raise(e)
    count = session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(WorkspaceMembership.custom_role_id == role.id)
    )
    return _custom_out(role, count or 0)


@router.delete("/{workspace_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_role(
    workspace_id: uuid.UUID, role_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    load_workspace_for_user(
        session, user, workspace_id, permission=Permission.ROLES_MANAGE
    )
    try:
        role = role_service.get_custom_role(
            session, workspace_id, role_id, exclusive=True
        )
        role_service.delete_role(session, role=role)
        session.commit()
    except RoleError as e:
        session.rollback()
        raise _raise(e)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    workspace_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[MemberOut]:
    load_workspace_for_user(session, user, workspace_id)
    rows = session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.invited_at, User.id)
    ).all()
    return [_member_out(m, u) for m, u in rows]


@router.patch("/{workspace_id}/members/{user_id}/role", response_model=MemberOut)
def set_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleAssignment,
    user: CurrentUser,
    session: DbSession,
) -> MemberOut:
    _, actor = load_workspace_for_user(
        session, user, workspace_id, permission=Permission.MEMBERS_MANAGE
    )
    try:
        if body.role_id is not None:
            choice = RoleChoice(
                custom=role_service.get_custom_role(session, workspace_id, body.role_id)
            )
        else:
            choice = RoleChoice(builtin=body.role)
        membership = role_service.assign_role(
            session,
            workspace_id=workspace_id,
            actor=actor,
            target_user_id=user_id,
            choice=choice,
        )
        session.commit()
    except RoleError as e:
        session.rollback()
        raise _raise(e)
    target_user = session.get(User, user_id)
    return _member_out(membership, target_user)
