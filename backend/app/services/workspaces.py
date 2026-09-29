from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, User, Workspace, WorkspaceMembership


class WorkspaceNameTaken(Exception):
    """The owner already owns a workspace with this name."""


def create_workspace(
    session: Session, *, name: str, owner: User, description: str | None = None
) -> Workspace:
    """Create a workspace and its canonical owner membership.

    Names are unique per owner, case-insensitively. Other users may reuse a
    name, and workspaces merely shared with the owner do not count.
    """
    # Lock the owner row so two concurrent creates by the same user cannot both
    # pass the duplicate check. A no-op on SQLite, which serialises writes anyway.
    session.execute(select(User.id).where(User.id == owner.id).with_for_update())

    taken = session.scalar(
        select(Workspace.id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == owner.id,
            WorkspaceMembership.role == Role.OWNER,
            func.lower(Workspace.name) == name.lower(),
        )
        .limit(1)
    )
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
