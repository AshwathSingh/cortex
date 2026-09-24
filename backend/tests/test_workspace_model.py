import uuid

from app.db.base import Base
from app.models import Role, User, Workspace, WorkspaceMembership


def test_workspace_models_share_auth_metadata():
    assert User.metadata is Base.metadata
    assert Workspace.metadata is Base.metadata
    assert WorkspaceMembership.metadata is Base.metadata
    assert {"users", "workspaces", "workspace_memberships"}.issubset(
        Base.metadata.tables
    )


def test_workspace_membership_shape_and_roles():
    membership = WorkspaceMembership(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        role=Role.EDITOR,
    )

    assert membership.role is Role.EDITOR
    assert (
        next(
            iter(WorkspaceMembership.__table__.c.user_id.foreign_keys)
        ).target_fullname
        == "users.id"
    )
