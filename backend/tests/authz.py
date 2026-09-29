"""Helpers for tests that call endpoints behind authentication.

Callers authenticate the way the app really does -- a session cookie backed by a
``user_sessions`` row -- so these helpers exercise the real
``get_current_user`` / ``load_workspace_for_user`` path rather than stubbing it.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Role, User, UserSession, Workspace, WorkspaceMembership
from app.security import hash_session_token, new_session_token


def make_user(session: Session, email: str) -> User:
    user = User(email=email, password_hash=None, display_name=email.split("@")[0])
    session.add(user)
    session.flush()
    return user


def make_workspace(session: Session, name: str, workspace_id: str | uuid.UUID) -> Workspace:
    """A workspace with an explicit id, so graph assertions can use the same one."""
    workspace = Workspace(id=uuid.UUID(str(workspace_id)), name=name)
    session.add(workspace)
    session.flush()
    return workspace


def grant(session: Session, workspace: Workspace, user: User, role: Role) -> None:
    session.add(
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=role)
    )


def authenticate(
    client: TestClient,
    sessions: sessionmaker[Session],
    user: User,
    *,
    expires_in: timedelta = timedelta(days=1),
) -> str:
    """Sign the caller in the way the app does: a real session row plus its cookie."""
    token = new_session_token()
    with sessions() as session:
        session.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(timezone.utc) + expires_in,
            )
        )
        session.commit()
    client.cookies.set(settings.session_cookie_name, token)
    return token


def sign_in_with_role(
    client: TestClient,
    sessions: sessionmaker[Session],
    workspace_id: str | uuid.UUID,
    role: Role | None,
    *,
    email: str = "member@example.com",
    workspace_name: str = "Test workspace",
) -> Workspace:
    """Create a user and a workspace, grant ``role`` (or nothing), and sign in.

    ``role=None`` creates the workspace without any membership for the caller --
    the "not a member" case.
    """
    with sessions() as session:
        user = make_user(session, email)
        workspace = make_workspace(session, workspace_name, workspace_id)
        if role is not None:
            grant(session, workspace, user, role)
        session.commit()
        session.refresh(user)
        session.refresh(workspace)

    authenticate(client, sessions, user)
    return workspace
