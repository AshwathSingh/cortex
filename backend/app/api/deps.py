"""Shared authenticated request dependencies."""

import uuid
from collections.abc import Collection
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.postgres import get_session
from app.models import Role, User, UserSession, Workspace, WorkspaceMembership
from app.security import hash_session_token

# Roles allowed to change a workspace's contents. A VIEWER may read the graph but
# must not trigger ingestion, which writes nodes.
WRITER_ROLES: frozenset[Role] = frozenset({Role.OWNER, Role.EDITOR})


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = session.scalar(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.expires_at > datetime.now(timezone.utc),
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_session)]


def load_workspace_for_user(
    session: Session,
    user: User,
    workspace_id: uuid.UUID,
    *,
    require: Collection[Role] | None = None,
) -> tuple[Workspace, Role]:
    """The workspace plus the caller's role on it, or 403.

    A workspace that does not exist and one the caller holds no role on return
    the same 403, so nobody can discover which workspaces exist. ``require``
    narrows that to a set of roles -- a member with the wrong role also gets 403,
    with a message naming what the action needs.
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
    if require is not None and role not in require:
        # Declaration order (OWNER, EDITOR, VIEWER), so the message reads by privilege.
        by_privilege = list(Role)
        allowed = " or ".join(r.value for r in sorted(require, key=by_privilege.index))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This action requires {allowed} access to the workspace",
        )
    return workspace, role
