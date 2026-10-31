"""Workspace invites (US-03).

Creating an invite returns the raw token exactly once; only its SHA-256 hash is
stored. Authorisation mirrors role assignment: whoever invites someone is handing
out a role, so the same guards apply -- only an owner may invite an owner, and an
inviter can't offer permissions they don't hold themselves.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    InviteStatus,
    Role,
    User,
    WorkspaceInvite,
    WorkspaceMembership,
)
from app.permissions import Permission, membership_permissions
from app.security import hash_invite_token, new_invite_token
from app.services.roles import (
    Conflict,
    Gone,
    NotFound,
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
    # Re-read and lock the inviter's own membership so a removal or role change that
    # committed (or is committing) since the route authorised them is honoured: a
    # removed member can't still mint an OWNER invite from a stale snapshot. Removal
    # and role changes write this same row, so they serialise against us.
    try:
        session.refresh(actor, with_for_update=True)
    except InvalidRequestError:  # removed while we waited
        raise NotPermitted("You no longer have access to this workspace")
    if Permission.MEMBERS_MANAGE not in membership_permissions(actor):
        raise NotPermitted("You no longer have permission to invite members")

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


def accept_invite(
    session: Session, *, token: str, user: User
) -> tuple[WorkspaceInvite, WorkspaceMembership]:
    """Redeem an invite token for ``user``.

    Any logged-in holder of the token may redeem it; the invite email is not
    matched against the account, since GitHub sign-in emails often differ.

    The pending -> accepted flip is a single conditional UPDATE, so two concurrent
    accepts can't both win. It and the membership insert share one transaction: any
    rejection leaves no membership row. If the user is already a member the invite
    is still consumed but no second row is created.

    Raises ``NotFound`` (404), ``Gone`` (410, expired) or ``Conflict`` (409, already
    accepted or revoked).
    """
    token_hash = hash_invite_token(token)
    now = datetime.now(timezone.utc)

    claimed = session.scalar(
        update(WorkspaceInvite)
        .where(
            WorkspaceInvite.token_hash == token_hash,
            WorkspaceInvite.status == InviteStatus.PENDING,
            WorkspaceInvite.expires_at > now,
        )
        .values(status=InviteStatus.ACCEPTED, accepted_at=now)
        .returning(WorkspaceInvite.id)
    )
    if claimed is None:
        _explain_rejection(session, token_hash, now)  # always raises

    invite = session.scalar(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.id == claimed)
        .execution_options(populate_existing=True)
    )
    # Upsert, not check-then-insert: two different invites for the same workspace
    # accepted at once by one user would both pass a "not a member yet" check and
    # the loser would hit the unique key. DO NOTHING keeps the existing membership
    # (and its role) untouched if there already is one.
    _insert = _dialect_insert(session)
    session.execute(
        _insert(WorkspaceMembership)
        .values(
            id=uuid.uuid4(),
            workspace_id=invite.workspace_id,
            user_id=user.id,
            role=invite.role,
            custom_role_id=invite.custom_role_id,
            invited_by=invite.invited_by,
            status="active",
        )
        .on_conflict_do_nothing(index_elements=["user_id", "workspace_id"])
    )
    membership = session.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == invite.workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .execution_options(populate_existing=True)
    )
    return invite, membership


def _dialect_insert(session: Session):
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # SQLite in tests
        from sqlalchemy.dialects.sqlite import insert
    return insert


def _explain_rejection(session: Session, token_hash: str, now: datetime):
    invite = session.scalar(
        select(WorkspaceInvite).where(WorkspaceInvite.token_hash == token_hash)
    )
    if invite is None:
        raise NotFound("This invitation link is not valid")
    if invite.status is InviteStatus.PENDING or invite.status is InviteStatus.EXPIRED:
        if invite.status is InviteStatus.PENDING:
            invite.status = InviteStatus.EXPIRED
            session.commit()  # keep the retirement even though we reject
        raise Gone("This invitation has expired; ask for a new one")
    if invite.status is InviteStatus.ACCEPTED:
        raise Conflict("This invitation has already been used")
    raise Conflict("This invitation has been revoked")
