from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, User, Workspace, WorkspaceMembership


class WorkspaceNameTaken(Exception):
    """The owner already owns a workspace with this name."""


def _lock_owner_and_find_duplicate(
    session: Session,
    *,
    owner: User,
    name: str,
    excluding_workspace_id=None,
):
    session.execute(select(User.id).where(User.id == owner.id).with_for_update())

    query = (
        select(Workspace.id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == owner.id,
            WorkspaceMembership.role == Role.OWNER,
            func.lower(Workspace.name) == name.lower(),
        )
        .limit(1)
    )
    if excluding_workspace_id is not None:
        query = query.where(Workspace.id != excluding_workspace_id)
    return session.scalar(query)


def create_workspace(
    session: Session, *, name: str, owner: User, description: str | None = None
) -> Workspace:
    """Create a workspace and its canonical owner membership.

    Names are unique per owner, case-insensitively. Other users may reuse a
    name, and workspaces merely shared with the owner do not count.
    """
    # Serialises creates and renames for one owner. A no-op on SQLite, which
    # serialises writes anyway.
    taken = _lock_owner_and_find_duplicate(session, owner=owner, name=name)
    if taken is not None:
        raise WorkspaceNameTaken(name)

    workspace = Workspace(name=name, description=description)
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMembership(
            user_id=owner.id,
            workspace_id=workspace.id,
            role=Role.OWNER,
        )
    )
    return workspace


def update_workspace(
    session: Session,
    *,
    workspace: Workspace,
    owner: User,
    name: str,
    description: str | None,
) -> Workspace:
    """Rename an owned workspace while preserving per-owner name uniqueness."""
    taken = _lock_owner_and_find_duplicate(
        session,
        owner=owner,
        name=name,
        excluding_workspace_id=workspace.id,
    )
    if taken is not None:
        raise WorkspaceNameTaken(name)

    workspace.name = name
    workspace.description = description
    session.flush()
    return workspace
