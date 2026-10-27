"""Workspace invites (US-03).

Creating an invite returns the raw token exactly once; only its SHA-256 hash is
stored. Authorisation mirrors role assignment: whoever invites someone is handing
out a role, so the same guards apply -- only an owner may invite an owner, and an
inviter can't offer permissions they don't hold themselves.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    InviteStatus,
    Role,
    User,
    WorkspaceInvite,
    WorkspaceMembership,
)
from app.security import hash_invite_token, new_invite_token
from app.services.roles import (
    Conflict,
    NotPermitted,
    RoleChoice,
    ensure_can_grant,
)

DEFAULT_ROLE = Role.EDITOR


def normalise_email(email: str) -> str:
    return email.strip().lower()


def create_invite(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    actor: WorkspaceMembership,
    email: str,
    choice: RoleChoice | None,
) -> tuple[WorkspaceInvite, str]:
    """Create a pending invite and return it with the raw, show-once token.

    Raises ``NotPermitted`` (403) for a role the inviter may not hand out and
    ``Conflict`` (409) if the invitee is already a member or already has a pending,
    unexpired invite. Caller must already hold ``members.manage``.
    """
    choice = choice or RoleChoice(builtin=DEFAULT_ROLE)
    if choice.is_owner and actor.role is not Role.OWNER:
        raise NotPermitted("Only an owner can invite someone as an owner")
    ensure_can_grant(actor, choice.permissions)

    email = normalise_email(email)
    now = datetime.now(timezone.utc)

    already_member = session.scalar(
        select(WorkspaceMembership.id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            func.lower(User.email) == email,
        )
        .limit(1)
    )
    if already_member is not None:
        raise Conflict(f"{email} is already a member of this workspace")

    # A pending invite past its expiry no longer counts: retire it so the partial
    # unique index lets a fresh one in.
    session.execute(
        update(WorkspaceInvite)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.email == email,
            WorkspaceInvite.status == InviteStatus.PENDING,
            WorkspaceInvite.expires_at <= now,
        )
        .values(status=InviteStatus.EXPIRED)
    )
    pending = session.scalar(
        select(WorkspaceInvite.id)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.email == email,
            WorkspaceInvite.status == InviteStatus.PENDING,
        )
        .limit(1)
    )
    if pending is not None:
        raise Conflict(f"{email} already has a pending invitation to this workspace")

    token = new_invite_token()
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=email,
        token_hash=hash_invite_token(token),
        role=choice.builtin,
        custom_role_id=choice.custom.id if choice.custom else None,
        invited_by=actor.user_id,
        expires_at=now + timedelta(days=settings.invite_ttl_days),
        status=InviteStatus.PENDING,
    )
    session.add(invite)
    try:
        session.flush()
    except IntegrityError:  # lost a race with a concurrent invite of the same email
        session.rollback()
        raise Conflict(f"{email} already has a pending invitation to this workspace")
    session.refresh(invite)
    return invite, token
