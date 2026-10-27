"""US-03: invite people to a workspace.

    POST /api/workspaces/{id}/invites   {"email": "...", "role": "EDITOR" | "role_id": "<uuid>"}

Needs ``members.manage``. ``role`` (built-in) and ``role_id`` (custom) are
alternatives; with neither the invite grants EDITOR. The response carries the raw
token once -- it is not stored and cannot be retrieved later. No email is sent;
the inviter shares the token with the invitee.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, model_validator

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.models import Role
from app.permissions import Permission
from app.services import invites as invite_service
from app.services import roles as role_service
from app.services.roles import RoleChoice, RoleError

router = APIRouter(prefix="/api/workspaces", tags=["invites"])


class InviteCreate(BaseModel):
    email: EmailStr
    role: Role | None = None
    role_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _at_most_one_role(self) -> "InviteCreate":
        if self.role is not None and self.role_id is not None:
            raise ValueError("Provide at most one of 'role' or 'role_id'")
        return self


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str  # built-in name, or the custom role's name
    role_id: uuid.UUID | None
    expires_at: datetime
    token: str  # shown once


@router.post(
    "/{workspace_id}/invites",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_invite(
    workspace_id: uuid.UUID,
    body: InviteCreate,
    user: CurrentUser,
    session: DbSession,
) -> InviteOut:
    _, actor = load_workspace_for_user(
        session, user, workspace_id, permission=Permission.MEMBERS_MANAGE
    )
    try:
        choice = None
        if body.role_id is not None:
            choice = RoleChoice(
                custom=role_service.get_custom_role(session, workspace_id, body.role_id)
            )
        elif body.role is not None:
            choice = RoleChoice(builtin=body.role)
        invite, token = invite_service.create_invite(
            session,
            workspace_id=workspace_id,
            actor=actor,
            email=str(body.email),
            choice=choice,
        )
        session.commit()
    except RoleError as e:
        session.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.custom_role.name if invite.custom_role else invite.role.value,
        role_id=invite.custom_role_id,
        expires_at=invite.expires_at,
        token=token,
    )
