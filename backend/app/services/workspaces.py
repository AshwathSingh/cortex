from sqlalchemy.orm import Session

from app.models import Role, User, Workspace, WorkspaceMembership


def create_workspace(session: Session, *, name: str, owner: User) -> Workspace:
    """Create a workspace and its canonical owner membership."""
    workspace = Workspace(name=name)
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
